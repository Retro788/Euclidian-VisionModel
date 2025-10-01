#! /bin/bash
# The script needs to be run on at least 4 nodes.

MEGATRON_PATH=${MEGATRON_PATH:-"/workspace/AIAK-Megatron"}

AIAK_TRAINING_PATH=${AIAK_TRAINING_PATH:-"/workspace/AIAK-Training-LLM"}

DATA_PATH=${DATA_PATH:-"/mnt/cluster/aiak-training-llm/dataset/mllm/demo/wds/"}

TOKENIZER_PATH=${TOKENIZER_PATH:-"/mnt/cluster/huggingface.co/Qwen/Qwen2.5-VL-72B-Instruct/"}

CHECKPOINT_PATH=${CHECKPOINT_PATH:-"/mnt/cluster/aiak-training-llm/qwen2_5-vl/qwen2_5-vl-72b-tp4-pp4-13172228"}

TENSORBOARD_PATH=${TENSORBOARD_PATH:-"/mnt/cluster/aiak-training-llm/tensorboard-log/qwen2_5-vl-72b"}

GPUS_PER_NODE=8

# Change for multinode config
MASTER_ADDR=${MASTER_ADDR:-"localhost"}
MASTER_PORT=${MASTER_PORT:-"6000"}
NNODES=${WORLD_SIZE:-"1"}
NODE_RANK=${RANK:-"0"}

DISTRIBUTED_ARGS=(
    --nproc_per_node $GPUS_PER_NODE
    --nnodes $NNODES
    --node_rank $NODE_RANK
    --master_addr $MASTER_ADDR
    --master_port $MASTER_PORT
)

# or you can setup qwen2.5-vl-72b by using the following command
MODEL_ARGS=(
    --model-name qwen2_5-vl-72b
)

DATA_ARGS=(
    --tokenizer-type HFTokenizer
    --hf-tokenizer-path $TOKENIZER_PATH
    --data-path $DATA_PATH
    --dataloader-type external
    --split 100,0,0
    --add-question-in-pretrain
    --enable-discard-sample
    --num-workers 16
    --chat-template default
)

TRAINING_ARGS=(
    --norm-epsilon 1e-6
    --training-phase pretrain
    --seq-length 8192
    --max-position-embeddings 8192
    --init-method-std 0.02
    --micro-batch-size 1
    --global-batch-size 512
    --lr 0.0002
    --min-lr 1.0e-5
    --clip-grad 1.0
    --weight-decay 0.01
    --optimizer adam
    --adam-beta1 0.9
    --adam-beta2 0.95
    --adam-eps 1e-05
    --train-iters 50000
    --lr-decay-iters 50000
    --lr-decay-style cosine
    --lr-warmup-fraction 0.002
    --initial-loss-scale 65536
    --bf16
    --load $CHECKPOINT_PATH
    --save $CHECKPOINT_PATH
    --save-interval 10000000
    --ckpt-format torch
    --dataloader-save ${CHECKPOINT_PATH}/dataloader
)

MODEL_PARALLEL_ARGS=(
    --attention-backend flash
    --pipeline-model-parallel-size 4
    --tensor-model-parallel-size 4
    --custom-pipeline-layers 13,17,22,28
    --disable-turn-off-bucketing
    --use-precision-aware-optimizer
    --optimizer-cpu-offload
    --optimizer-offload-fraction 1.0
    --use-distributed-optimizer
    --overlap-grad-reduce
    --overlap-param-gather
    --distributed-backend nccl
)

LOGGING_ARGS=(
    --log-interval 1
    --tensorboard-dir ${TENSORBOARD_PATH}
    --log-timers-to-tensorboard
)

if [ -n "${WANDB_API_KEY}" ]; then
    LOGGING_ARGS+=(
        --wandb-project ${WANDB_PROJECT}
        --wandb-exp-name ${WANDB_NAME}
    )
fi

PYTHONPATH=$MEGATRON_PATH:$AIAK_TRAINING_PATH:$PYTHONPATH \
    torchrun ${DISTRIBUTED_ARGS[@]} \
    $AIAK_TRAINING_PATH/aiak_training_llm/train.py \
    ${MODEL_ARGS[@]} \
    ${DATA_ARGS[@]} \
    ${IMG_ARGS[@]} \
    ${TRAINING_ARGS[@]} \
    ${MODEL_PARALLEL_ARGS[@]} \
    ${LOGGING_ARGS[@]}