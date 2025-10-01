"""utils for sft"""
import logging

from typing import TYPE_CHECKING, List, Optional, Union, Any, Type
from dataclasses import dataclass

import torch
from torch.utils.data import DataLoader
from transformers.utils import PaddingStrategy

from datasets.distributed import split_dataset_by_node

from megatron.core import mpu, tensor_parallel
from megatron.core.transformer.enums import AttnMaskType
from megatron.core.packed_seq_params import PackedSeqParams

from megatron.legacy.data.data_samplers import MegatronPretrainingRandomSampler

from aiak_training_llm.utils import get_args, get_tokenizer, constants
from aiak_training_llm.data import DataCollatorForSupervisedDataset
from aiak_training_llm.tokenizer import AutoTokenizerFromHF


if TYPE_CHECKING:
    from datasets import Dataset, IterableDataset
logger = logging.getLogger(__name__)


######## utils for build dataset ########
def get_dataset_blend_from_list(dataset_names: Optional[List[str]]) -> Optional[List[str]]:
    """get dataset from list"""
    if dataset_names is None:
        return None

    return [_dataset_name.strip() for _dataset_name in dataset_names]


def _cyclic_iter(iter):
    """cyclic iteration"""
    while True:
        for x in iter:
            yield x


def build_sft_data_collator(
        cls: Type[DataCollatorForSupervisedDataset],
        **kwargs
    ) -> DataCollatorForSupervisedDataset:
    """build data collator for sft"""
    args = get_args()
    tokenizer = get_tokenizer()

    assert isinstance(tokenizer, AutoTokenizerFromHF), \
        f"Only support HFTokenizer for sft, but got {args.tokenizer_type}."

    pad_to_multiple_of = 1
    # When using sequence parallel, sequence will further be split by TP size
    # When using context parallel, sequence is split by CP size as well
    pad_to_multiple_of *= args.tensor_model_parallel_size if args.sequence_parallel else 1
    pad_to_multiple_of *= (2 * args.context_parallel_size) if args.context_parallel_size > 1 else 1
    padding = PaddingStrategy.LONGEST if args.variable_seq_lengths else PaddingStrategy.MAX_LENGTH
    if args.tp_comm_overlap:
        padding = PaddingStrategy.MAX_LENGTH
        logger.warning(f"Due to the fact that tp_comm_overlap only supports fixed length, "
                       f"the padding strategy has been changed from variable length to maximum length.")

    data_collator = cls(
        tokenizer=tokenizer.hf_tokenizer(),
        label_pad_token_id=constants.IGNORE_INDEX,
        pad_to_multiple_of=pad_to_multiple_of,
        padding=padding,
        max_length=args.seq_length,
        **kwargs
    )
    return data_collator


def _build_cylic_iterator(
    dataset: Union["Dataset", "IterableDataset"],
    consumed_samples: int,
    data_collator: DataCollatorForSupervisedDataset):
    """build data iterator for sft"""
    if dataset is None:
        return None

    args = get_args()

    _dataloader_kwargs = {}
    if args.sft_data_streaming:
        # split distributed dataset for streaming
        dataset = split_dataset_by_node(
            dataset=dataset,
            rank=mpu.get_data_parallel_rank(),
            world_size=mpu.get_data_parallel_world_size(),
        )

        dataset = dataset.shuffle(
            buffer_size=args.streaming_buffer_size,
            seed=args.seed,
        )

        _dataloader_kwargs = dict(
            batch_size=args.micro_batch_size,
        )
    else:
        # build distribued sampler for non-streaming dataset
        _batch_sampler = MegatronPretrainingRandomSampler(
            dataset,
            total_samples=len(dataset),
            consumed_samples=consumed_samples, # not support for streaming now!
            micro_batch_size=args.micro_batch_size,
            data_parallel_rank=mpu.get_data_parallel_rank(),
            data_parallel_size=mpu.get_data_parallel_world_size(),
            data_sharding=args.data_sharding,
        )

        _dataloader_kwargs = dict(
            batch_sampler=_batch_sampler,
            persistent_workers=True if args.num_workers > 0 else False,
        )

    dataloader = DataLoader(
        dataset,
        collate_fn=data_collator,
        num_workers=args.num_workers,
        pin_memory=True,
        **_dataloader_kwargs,
    )

    # use cyclic_iter to avoid stop when dataloader is empty
    data_iterator = iter(_cyclic_iter(dataloader))
    return data_iterator


def build_sft_cyclic_iterators(
    train_ds: Optional[Union["Dataset", "IterableDataset"]],
    valid_ds: Optional[Union["Dataset", "IterableDataset"]],
    test_ds: Optional[Union["Dataset", "IterableDataset"]],
    data_collator: Optional[DataCollatorForSupervisedDataset],
):
    """build data iterators for sft"""
    args = get_args()
    train_iter = _build_cylic_iterator(train_ds, args.consumed_train_samples, data_collator)
    valid_iter = _build_cylic_iterator(valid_ds, 0 if args.skip_train else args.consumed_valid_samples, data_collator)
    test_iter = _build_cylic_iterator(test_ds, 0, data_collator)
    return train_iter, valid_iter, test_iter


######## utils for get_batch ########
def _get_position_ids(data: torch.Tensor):
    """create position ids"""
    current_device = data.device
    _, seq_length = data.shape

    position_ids = torch.arange(seq_length, dtype=torch.long, device=current_device)
    position_ids = position_ids.unsqueeze(0).expand_as(data)
    return position_ids


def _get_attention_mask(attention_mask: torch.Tensor) -> torch.Tensor:
    """create attention mask"""
    args = get_args()
    current_device = attention_mask.device
    batch_size, seq_length = attention_mask.shape

    # Only used attn_mask when attn_mask_type in [padding, padding_causal, arbitrary] in TE
    # TODO: for multi-acceleator, maybe we should update attn_mask_type and attention_mask shape

    attn_mask_type = AttnMaskType.causal
    if args.context_parallel_size > 1:
        # Firstly, context parallel only support causal mask in TE now.
        # Secondly, when context-parallel is enabled, the input data is of a relatively long length,
        # and micro-batch-size does not need to be increased, nor padding occurs
        # create causal mask here, shape [B, 1, S, S].
        attention_mask = torch.tril(
            torch.ones((batch_size, seq_length, seq_length), dtype=torch.long, device=current_device)
        )
        attention_mask.unsqueeze_(1)
        attention_mask = (attention_mask < 0.5).bool()
    else:
        # create mask for te, shape [B, 1, 1, S]. attn_mask_type is padding_causal or causal.
        attention_mask.unsqueeze_(1).unsqueeze_(1)
        attention_mask = (attention_mask < 0.5).bool()
        if torch.any(attention_mask == True).item():
            attn_mask_type = AttnMaskType.padding_causal

    return attention_mask, attn_mask_type


def _get_packed_sequence_params(attention_mask: torch.Tensor) -> PackedSeqParams:
    """create packed sequence params"""
    # assume micro_batch_size == 1
    assert attention_mask.shape[0] == 1, "attention_mask should be of shape [1, S]"

    packed_seq_params = PackedSeqParams()
    packed_seq_params.qkv_format = "thd"

    # calculate cu_seqlens_q
    # example: mask = [[1, 1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 0, 0]]
    # expacted cu_seqlens_q = [0, 2, 5, 7, 8, 11, 13]
    max_num = attention_mask.max().item()
    reduced_mask = torch.bincount(attention_mask.view(-1), minlength=max_num + 1)
    reduced_mask = reduced_mask[1:].to(dtype=torch.int32, device=attention_mask.device)

    cu_seqlens = reduced_mask.cumsum(dim=0).to(torch.int32)
    zero = torch.zeros(1, dtype=torch.int32, device=attention_mask.device)
    # The lengths of padding tokens must also be taken into account in cu_seqlens;
    # otherwise, the attention calculation will be incorrect.
    cu_seqlens[-1] = attention_mask.shape[1]
    cu_seqlens = torch.cat((zero, cu_seqlens))

    packed_seq_params.cu_seqlens_q = cu_seqlens
    packed_seq_params.cu_seqlens_kv = cu_seqlens # just for self-attention
    packed_seq_params.max_seqlen_q = reduced_mask.max().item()
    packed_seq_params.max_seqlen_kv = packed_seq_params.max_seqlen_q

    return packed_seq_params, AttnMaskType.padding_causal


def get_batch_on_this_tp_rank(data_iterator):
    """get batch on this tp rank"""
    args = get_args()
    tokenizer = get_tokenizer()

    if data_iterator is not None:
        data = next(data_iterator)
    else:
        data = None

    # broadcast required keys across tp
    required_keys = ["attention_mask"]

    if args.pipeline_model_parallel_size == 1:
        required_keys += ["input_ids", "labels"] + (["loss_mask"] if not args.eod_mask_loss else [])

    elif mpu.is_pipeline_first_stage():
        required_keys.append("input_ids")

    elif mpu.is_pipeline_last_stage():
        required_keys += ["input_ids", "labels"] + (["loss_mask"] if not args.eod_mask_loss else [])

    data_b = tensor_parallel.broadcast_data(required_keys, data, torch.int64)

    # tokens & position ids
    tokens = data_b["input_ids"].long() if "input_ids" in data_b else None
    position_ids = None
    if tokens is not None:
        position_ids = _get_position_ids(tokens)

    # set AIAK-ACCELERATOR custom_roll
    try:
        from aiak_accelerator.multiacc_engine import \
                multiacc_utils
    except ImportError:
        multiacc_utils = None

    if multiacc_utils is not None:
        if multiacc_utils["custom_roll"] is not None:
            torch.roll = multiacc_utils["custom_roll"]

    # labels & loss mask
    labels = data_b["labels"].long() if "labels" in data_b else None
    if labels is not None:
        labels = torch.roll(labels, shifts=-1, dims=1)
        labels[:, -1] = constants.IGNORE_INDEX
        # labels[labels == tokenizer.pad] == constants.IGNORE_INDEX
        # labels[labels == tokenizer.eos] == constants.IGNORE_INDEX

    # create loss mask
    loss_mask = data_b["loss_mask"].long() if "loss_mask" in data_b else None
    if loss_mask is not None:
        # pp last && not eod_mask_loss
        loss_mask = torch.roll(loss_mask, shifts=-1, dims=1)
        loss_mask[:, -1] = 0

    elif labels is not None:
        # pp last && eod_mask_loss
        assert args.eod_mask_loss, "eod_mask_loss should be true here!"
        loss_mask = torch.ones(labels.size(), dtype=torch.float, device=labels.device)
        loss_mask[labels == constants.IGNORE_INDEX] = 0.0
        loss_mask[labels == tokenizer.pad] = 0.0
        loss_mask[labels == tokenizer.eos] = 0.0

    # attention mask
    attention_mask = None
    attn_mask_type = None
    packed_seq_params = None

    if not args.packing_sft_data:
        attention_mask, attn_mask_type = _get_attention_mask(data_b["attention_mask"].long())
    else:
        packed_seq_params, attn_mask_type = _get_packed_sequence_params(data_b["attention_mask"].long())

    batch = {
        "tokens": tokens,
        "labels": labels,
        "loss_mask": loss_mask,
        "position_ids": position_ids,
        "attention_mask": attention_mask,
        "attn_mask_type": attn_mask_type,
        "packed_seq_params": packed_seq_params
    }

    return batch
