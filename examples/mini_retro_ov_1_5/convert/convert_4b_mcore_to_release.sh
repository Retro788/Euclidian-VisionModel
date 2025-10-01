AIAK_TRAINING_PATH="${AIAK_TRAINING_PATH:-/workspace/MiniRetro-OneVision-1.5}"
AIAK_MAGATRON_PATH="${AIAK_MAGATRON_PATH:-${AIAK_TRAINING_PATH%/}/aiak_megatron}"
CONVERT_CHECKPOINT_PATH="$AIAK_TRAINING_PATH/tools/convert_checkpoint"

LOAD=$1
SAVE=$2
TP=$3
PP=$4


bash $AIAK_TRAINING_PATH/examples/mini_retro_ov_1_5/convert/convert_4b_mcore_to_hf.sh \
    $LOAD tmp_hf $TP $PP

bash $AIAK_TRAINING_PATH/examples/mini_retro_ov_1_5/convert/convert_4b_hf_to_mcore.sh \
    tmp_hf $SAVE $TP $PP

rm -rf tmp_hf
