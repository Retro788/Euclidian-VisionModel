"""qwen model provider"""

from copy import deepcopy
from dataclasses import asdict

from megatron.core import mpu
from megatron.core.transformer.spec_utils import import_module

from aiak_training_llm.utils import get_args, build_transformer_config, print_rank_0
from aiak_training_llm.utils.constants import VisionLanguageModelFamilies

from aiak_training_llm.models.factory import register_model_provider

from .qwen2_vl_model import Qwen2VLModel
from .qwen2_vl_layer_spec import (
    get_adapeter_layer_with_spec,
    get_vision_layer_with_spec,
    get_qwen_layer_with_spec,
)
from .qwen2_vl_config import (
    get_adapeter_config,
    get_vision_config,
)

import torch

@register_model_provider(model_family=[VisionLanguageModelFamilies.QWEN2_VL,
                                        VisionLanguageModelFamilies.QWEN2_5_VL])
def qwen2vl_model_provider(
    pre_process: bool = True,
    post_process: bool = True,
    add_encoder: bool = True,
    add_decoder: bool = True,
    parallel_output: bool = True,

) -> Qwen2VLModel:
    """Builds the qwen2-vl model.

    Args:
        pre_process (bool, optional): Set to true if you need to compute embedings. Defaults to True.
        post_process (bool, optional): Set to true if you need to want to compute output logits/loss. Defaults to True.
        parallel_output (bool): whether to allgather the output logits

    Returns:
        Qwen2VLModel: The returned model
    """
    args = get_args()

    print_rank_0(f'building {args.model_name} model ...')

    config = build_transformer_config(args)

    language_config = deepcopy(config)
    vision_config = deepcopy(config)
    adapter_config = deepcopy(config)

    from aiak_training_llm.models import get_model_family
    model_family = get_model_family(args.model_name)
    for k, v in asdict(get_vision_config(model_family, args.model_name)).items():
        setattr(vision_config, k, v)
    for k, v in asdict(get_adapeter_config(model_family)).items():
        setattr(adapter_config, k, v)

    setattr(language_config, "image_token_id", 151655)
    setattr(language_config, "video_token_id", 151656)

    # FIXME: fix this if model_type is encoder_and_decoder
    if args.encoder_pipeline_model_parallel_size in [0, None]:
        vision_config.pipeline_model_parallel_size = 1
        vision_config.tensor_model_parallel_size = 1
        vision_config.sequence_parallel = False
        vision_config.tp_comm_overlap = False
        vision_config.context_parallel_size = 1
        vision_config.context_parallel_ulysses_degree = 1
        add_encoder = mpu.is_pipeline_first_stage()
        add_decoder = True
    else:
        assert (
            args.encoder_pipeline_model_parallel_size == 1
        ), "vision model and projection can only live on 1 pipeline stage."
        vision_config.pipeline_model_parallel_size = args.encoder_pipeline_model_parallel_size
        if args.encoder_tensor_model_parallel_size > 0:
            vision_config.tensor_model_parallel_size = args.encoder_tensor_model_parallel_size

        # Make sure the vision model does not inherit first and last pipeline num layers from the language model.
        vision_config.first_pipeline_num_layers = vision_config.last_pipeline_num_layers = None

        # TODO: Vision model and projection do not use SP/CP yet.
        vision_config.sequence_parallel = False
        vision_config.context_parallel_size = 1
        vision_config.tp_comm_overlap = False

    if args.use_legacy_models:
        raise ValueError("Classic Megatron-LM models are not supported.")

    if args.spec is not None:
        language_layer_spec = import_module(args.spec)
    else:
        adapter_layer_spec = get_adapeter_layer_with_spec()
        vision_layer_spec = get_vision_layer_with_spec()
        language_layer_spec = get_qwen_layer_with_spec(args.qk_layernorm)

    model = Qwen2VLModel(
        language_config=language_config,
        vision_config=vision_config,
        adapter_config=adapter_config,
        language_layer_spec=language_layer_spec,
        vision_layer_spec=vision_layer_spec,
        adapter_layer_spec=adapter_layer_spec,
        language_vocab_size=args.padded_vocab_size,
        language_max_sequence_length=args.max_position_embeddings,
        pre_process=pre_process,
        post_process=post_process,
        add_encoder=add_encoder,
        add_decoder=add_decoder,
        fp16_lm_cross_entropy=args.fp16_lm_cross_entropy,
        parallel_output=parallel_output,
        share_embeddings_and_output_weights=not args.untie_embeddings_and_output_weights,
        language_position_embedding_type=args.position_embedding_type,
        language_rotary_percent=args.rotary_percent,
        language_rotary_base=args.rotary_base,
        seq_len_interpolation_factor=args.rotary_seq_len_interpolation_factor,
    )

    if args.trainable_modules != ['all']:
        train_language_model = "language_model" in args.trainable_modules
        train_vision_model = "vision_model" in args.trainable_modules
        train_adapter = "adapter" in args.trainable_modules
        model.freeze(freeze_language_model=not train_language_model,
                    freeze_vision_model=not train_vision_model,
                    freeze_adapter=not train_adapter)

    return model
