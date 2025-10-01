AIAK_TRAINING_PATH="${AIAK_TRAINING_PATH:-/workspace/MiniRetro-OneVision-1.5}"
AIAK_MAGATRON_PATH="${AIAK_MAGATRON_PATH:-${AIAK_TRAINING_PATH%/}/aiak_megatron}"
CONVERT_CHECKPOINT_PATH="$AIAK_TRAINING_PATH/tools/convert_checkpoint"

LOAD=$1
SAVE=$2
TP=1
PP=1
EP=8

mkdir -p ./tmp/
SAVE_LANGUAGE_MODEL=./tmp/language-mcore
SAVE_VISION_MODEL=./tmp/vision-model-mcore
SAVE_ADAPTER=./tmp/adapter-mcore
SAVE_PATCH=./tmp/patch-mcore



python $CONVERT_CHECKPOINT_PATH/model.py \
    --load_platform=mcore \
    --megatron_path $AIAK_MAGATRON_PATH \
    --save_platform=huggingface \
    --common_config_path=$CONVERT_CHECKPOINT_PATH/config/mini-retro-ov-1.5-30b-a3b/qwen3.json \
    --tensor_model_parallel_size=$TP \
    --pipeline_model_parallel_size=$PP \
    --num_experts=128 \
    --expert_parallel_size=$EP \
    --load_ckpt_path=$LOAD \
    --save_ckpt_path=$SAVE_LANGUAGE_MODEL \
    --safetensors \
    --no_save_optim \
    --no_load_optim

if [[ $PP -eq 1 ]]; then
    LOAD_PATH=$LOAD
else
    LOAD_PATH=$LOAD/tmp/
    mkdir -p $LOAD_PATH
    for ((i=0;i<$TP;i++)); do
        from=`printf "mp_rank_%02d_000" $i`
        to=`printf "mp_rank_%02d" $i`
        cp -r $LOAD/$from $LOAD_PATH/$to
    done
fi

python $CONVERT_CHECKPOINT_PATH/model.py \
    --load_platform=mcore \
    --save_platform=huggingface \
    --megatron_path $AIAK_MAGATRON_PATH \
    --common_config_path=$CONVERT_CHECKPOINT_PATH/config/mini-retro-ov-1.5-30b-a3b/vision-model.json \
    --tensor_model_parallel_size=$TP \
    --load_ckpt_path=$LOAD_PATH \
    --save_ckpt_path=$SAVE_VISION_MODEL \
    --safetensors \
    --no_save_optim \
    --no_load_optim

    # --pipeline_model_parallel_size=$PP \
    # --num_experts=128 \
    # --expert_parallel_size=$EP \

if [[ $LOAD != $LOAD_PATH ]]; then
    rm -rf $LOAD_PATH
fi

# adapter
python $CONVERT_CHECKPOINT_PATH/custom/mini_retroov_1_5_30b_a3b/adapter.py \
    --load_platform=mcore \
    --save_platform=huggingface \
    --megatron_path $AIAK_MAGATRON_PATH \
    --common_config_path=$CONVERT_CHECKPOINT_PATH/config/mini-retro-ov-1.5-30b-a3b/adapter.json \
    --tensor_model_parallel_size=$TP \
    --pipeline_model_parallel_size=$PP \
    --load_ckpt_path=$LOAD \
    --save_ckpt_path=$SAVE_ADAPTER

# vision patch
python $CONVERT_CHECKPOINT_PATH/custom/mini_retroov_1_5_30b_a3b/vision_patch.py \
    --load_platform=mcore \
    --save_platform=huggingface \
    --megatron_path $AIAK_MAGATRON_PATH \
    --tensor_model_parallel_size=$TP \
    --common_config_path=$CONVERT_CHECKPOINT_PATH/config/mini-retro-ov-1.5-30b-a3b/vision-patch.json \
    --load_ckpt_path=$LOAD \
    --save_ckpt_path=$SAVE_PATCH

# merge
python $CONVERT_CHECKPOINT_PATH/custom/mini_retroov_1_5_30b_a3b/merge_huggingface.py \
    --megatron_path $AIAK_MAGATRON_PATH \
    --language_model_path $SAVE_LANGUAGE_MODEL \
    --vision_model_path $SAVE_VISION_MODEL \
    --vision_patch $SAVE_PATCH \
    --adapter_path $SAVE_ADAPTER \
    --save_ckpt_path $SAVE


rm -rf $SAVE_LANGUAGE_MODEL
rm -rf $SAVE_VISION_MODEL
rm -rf $SAVE_ADAPTER
rm -rf $SAVE_PATCH
