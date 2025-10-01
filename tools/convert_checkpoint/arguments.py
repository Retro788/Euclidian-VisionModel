#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################

"""argparse"""

import argparse

_GLOBAL_ARGS = None


def set_args(args):
    global _GLOBAL_ARGS
    _GLOBAL_ARGS = args


def parse_args(title=None):
    global _GLOBAL_ARGS
    if _GLOBAL_ARGS is not None:
        return _GLOBAL_ARGS
    """Parse all arguments."""
    parser = argparse.ArgumentParser(description='Aiak-Tool Arguments',
                                     allow_abbrev=False)
    _add_checkpoint_args(parser)
    _add_common_args(parser)
    _add_huggingface_args(parser)
    _add_megatron_args(parser)

    args = parser.parse_args()
    if args.convert_to_fp8:
        assert args.load_platform == 'mcore' and args.save_platform == 'huggingface', \
                "convert_to_fp8 only support mcore to huggingface"
    if title is None:
        _GLOBAL_ARGS = args
        return _GLOBAL_ARGS
    else:
        for group in parser._action_groups:
            if group.title == title:
                group_dict={item.dest: getattr(args, item.dest, None) for item in group._group_actions}
                _GLOBAL_ARGS = argparse.Namespace(**group_dict)
                return _GLOBAL_ARGS
        _GLOBAL_ARGS = argparse.Namespace()
        return _GLOBAL_ARGS


def _add_checkpoint_args(parser):
    group = parser.add_argument_group(title='checkpoint')

    group.add_argument('--load_platform', type=str, default=None,
                       choices=['huggingface', 'megatron', 'mcore'])
    group.add_argument('--save_platform', type=str, default=None,
                       choices=['huggingface', 'megatron', 'mcore'])
    group.add_argument('--load_ckpt_path', type=str, default=None,
                       help='path to load checkpoint')
    group.add_argument('--save_ckpt_path', type=str, default=None,
                       help='path to save checkpoint')
    group.add_argument('--common_config_path', type=str, default=None,
                       help='path to common config')
    group.add_argument("--megatron_path", type=str, default=None,
                       help="Base directory of Megatron repository")
    group.add_argument('--no_load_optim', action='store_true',
                       help='do not convert optimizer')
    group.add_argument('--no_save_optim', action='store_true',
                       help='do not save optimizer')
    group.add_argument('--model_type_custom', type=str, default=None,
                       help='custom model type')
    group.add_argument('--safetensors', action='store_true',
                       help='Use [safetensors](https://huggingface.co/docs/safetensors).')
    group.add_argument('--convert_to_fp8', action='store_true',
                       help='Convert float16 weights to fp8')
    group.add_argument('--quant_method', type=str, default='te', choices=['te', 'pt', 'aiak'],
                       help='The quantization method to use. Choices: [te, pt, aiak].')
    group.add_argument('--amax_epsilon', type=float, default=0.0,
                       help=("Epsilon value added to the amax calculation to avoid division by zero "
                             "when converting to FP8. Only used in Transformer Engine FP8 conversion.")
    )
    group.add_argument('--force_pow_2_scales', action='store_true',
                       help=("Force power of 2 scales, only used in Transformer Engine FP8 conversion.")
    )
    group.add_argument('--pretrain_as_fp8', action='store_true',
                       help='Run pretrain as fp8, only used for hf to mcore when '
                       'saved checkpoint is bf16 and pretrain as fp8')

    group.add_argument('--fp8_quant_transfer_type', type=str, default="float32", choices=["float32", "bfloat16"],
                       help='The transfer dtype when convert from hf fp8 to mcore fp8')


def _add_common_args(parser):
    group = parser.add_argument_group(title='common')

    group.add_argument('--torch_dtype', type=str, choices=["float16", "float32", "bfloat16"],
                       help='target torch dtype')
    group.add_argument('--vocab_size', type=int, default=None, help='vocab size')
    group.add_argument('--vpp-scheduler', type=str, default=None,
                       choices=["dualpipev"],
                       help='By default, the original 1F1B scheduling method is used. When selecting DualPipeV, '
                            'the effect can be referred to at https://hackmd.io/@ufotalent/r1lVXsa9Jg')
    group.add_argument('--num-virtual-stages-per-pipeline-rank', type=int, default=None,
                       help='Number of virtual pipeline stages per pipeline parallelism rank')
    group.add_argument('--decoder-first-pipeline-num-layers',
                       type=int, default=None,
                       help=('The number of transformer layers on the first pipeline stage of the decoder. '
                       'Default None is even split of transformer layers across all pipeline stages'))
    group.add_argument('--decoder-last-pipeline-num-layers',
                       type=int, default=None,
                       help=('The number of transformer layers on the last pipeline stage of the decoder. '
                       'Default None is even split of transformer layers across all pipeline stages'))

def _add_megatron_args(parser):
    """
    Add MegaTron related parameters to the parser.

    Args:
        parser (ArgumentParser, str): ArgumentParser object or parameter string, used to add MegaTron related parameters.

    Returns:
        None, void: No return value, directly modify the passed ArgumentParser object.
    """
    group = parser.add_argument_group(title='megatron')

    group.add_argument('--use_distributed_optimizer', action='store_true',
                       help='use distributed optimizer')
    group.add_argument('--tensor_model_parallel_size', type=int, default=1,
                       help='target tensor model parallel size')
    group.add_argument('--pipeline_model_parallel_size', type=int, default=1,
                       help='target pipeline model parallel size')
    group.add_argument('--data_parallel_size', type=int, default=1,
                       help='target data parallel size')
    group.add_argument('--expert_parallel_size', type=int, default=None,
                       help='target expert parallel size')
    group.add_argument('--expert_tensor_parallel_size', type=int, default=None,
                       help='Degree of expert model parallelism. Default is None, '
                       'which will be set to the value of --tensor-model-paralle-size.')
    group.add_argument('--pad_vocab_size_to', type=int, default=None,
                       help='Pad the vocab size to this value.'
                            'This value must be greater than the initial size of the tokenizer'
                            ', needs to be divisible by TP size and `make-vocab-size-divisible-by`.')
    group.add_argument('--custom_pipeline_layers', type=str, default=None,
                       help='add by aiak for pp layer imbalance.For example 19,20,20,21.'
                       '19 for stage0 layers, 20 for stage1 layers...')
    group.add_argument('--num_layers_per_virtual_pipeline_stage', type=int, default=None,
                       help='Number of layers per virtual pipeline stage')
    group.add_argument('--transformer_impl', default='transformer_engine',
                       choices=['local', 'transformer_engine'],
                       help='Which Transformer implementation to use when load or save mcore checkpoint.'
                            'Only support `transformer_engine` now.')
    group.add_argument('--num_experts', type=int, default=None,
                       help='Number of Experts in MoE (None means no MoE)')
    group.add_argument('--checkpoint-format', type=str, default=None,
                       help='hf checkpoint format end with safetensors')
    group.add_argument('--max_workers', type=int, default=1,
                       help='thread for checkpoint converting')
    group.add_argument('--no-te', action='store_true',
                       help='do not use transformer engine')
    group.add_argument('--moe-grouped-gemm', action='store_true',
                       help='use grouped gemm in moe')
    group.add_argument('--resume-convert', action='store_true',
                       help='resume checkpoint converting when failed')
    group.add_argument('--cache-path', type=str, default=None,
                       help='cache path used during conversion')
    group.add_argument('--layer-for-test', type=str, default=None,
                       help='get specific layer from checkpoint for test')
    group.add_argument('--num-experts-for-test', type=int, default=None,
                       help='Number of Experts in MoE for test')
    group.add_argument('--sub-num-layers-for-save', type=int, default=None,
                       help='number of layers for saving each time')
    group.add_argument('--save-sub-checkpoint-by-pp', action='store_true',
                       help='save sub checkpoints by pipeline parallel')


def _add_huggingface_args(parser):
    group = parser.add_argument_group(title='huggingface')
    pass
