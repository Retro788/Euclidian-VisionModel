""" Convert dataset into WebDataset (WDS) format """
import argparse
import json
import os
import yaml
import webdataset as wds
from tqdm import tqdm
import random
from megatron.energon.epathlib import EPath
from megatron.energon.flavors import BaseWebdatasetFactory
from megatron.energon.flavors.webdataset import MAIN_FOLDER_NAME

def sample_loader_template(media: str=None):
    """Returns a template for a sample_loader.py file."""
    return "\n".join([
        "def sample_loader(sample: dict) -> dict:",
        "    messages=[]",
        "    system=None",
        "    for message in sample['json']['texts']:",
        "        assert message['role'] in ['system','user','assistant']",
        "        if message['role'] == 'system':",
        "            system=message['content']",
        "            continue",
        "        messages.append(dict(",
        "            role=message['role'],",
        "            content=message['content']",
        "        ))",
        "    video = []",
        "    image = []",
        "    if sample['json']['media'] == 'video':",
        "        for name in sample['json']['name']:",
        "            video.append(sample.get(name))",
        "    elif sample['json']['media'] == 'image':",
        "        for name in sample['json']['name']:",
        "            image.append(sample.get(name))",
        "    return dict(",
        "        __key__=sample['__key__'],",
        "        __restore_key__=sample['__restore_key__'],",
        "        video=video if len(video) > 0 else None,",
        "        image=image if len(image) > 0 else None," if media == 'mix' else "",
        "        system=system,",
        "        messages=messages,",
        "    )",
        "def part_filter(part: str) -> bool:",
        "    return True",
    ])

def construct_sample(args, vision, paths, index, entry):
    """ construct webdataset sample """
    assert vision == 'image' or vision == 'video'
    directory = args.image_dir if vision == 'image' else args.video_dir

    vision_data = {}
    vision_name = []

    for i, path in enumerate(paths):
        full_path = os.path.join(directory, path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Media file not found: {full_path}")
        try:
            with open(full_path, "rb") as vision_file:
                vision_data.update({str(i) + '_' + os.path.basename(path) : vision_file.read()})
                vision_name.append(str(i) + '_' + os.path.basename(path))
        except IOError as e:
            raise IOError(f"Failed to read media file {full_path}: {e}")

    content = {
        "texts": entry[args.columns_messages],
        "media": vision,
        "name": vision_name
    }
    sample = {
        "__key__": vision + '_' + str(index),
        **vision_data,
        "json": json.dumps(content).encode("utf-8"),
    }
    return sample

def convert_to_wds(args):
    """ Convert dataset to wds format """
    assert args.media in ['video', 'image', 'mix'], f"Invalid media type: {args.media}"

    if args.media == "video":
        assert args.video_dir is not None
    if args.media == "image":
        assert args.image_dir is not None
    if args.media == "mix":
        assert args.video_dir is not None or args.image_dir is not None, "At least one media directory required for mix mode"

    if not os.path.exists(args.output_dir):
        os.mkdir(args.output_dir)

    with open(args.json_file, 'r') as f:
        data = json.load(f)
    random.shuffle(data)

    tar = os.path.join(args.output_dir, 'pretrain-%d.tar')
    with wds.ShardWriter(tar, maxcount=args.maxcount, maxsize=args.maxsize) as shard_writer:
        for index, entry in enumerate(tqdm(data)):
            if args.media == 'image':
                image_path = entry.get('image')
                if image_path is None:
                    images = entry.get('images')
                    if images is None or len(images) == 0:
                        raise ValueError(f"No image path found in entry {index}")
                    image_path = images[0]
                with open(os.path.join(args.image_dir, image_path), "rb") as img_file:
                    image_data = img_file.read()
                sample = {
                    "__key__": entry.get('id', image_path).replace('.', '_'),
                    "jpg": image_data,
                    "json": json.dumps(entry[args.columns_messages]).encode("utf-8"),
                }
            else:
                video_paths = [entry.get('video')] if entry.get('video') is not None else entry.get('videos')
                image_paths = [entry.get('image')] if entry.get('image') is not None else entry.get('images')

                if video_paths is not None:
                    sample = construct_sample(args, 'video', video_paths, index, entry)
                elif image_paths is not None:
                    sample = construct_sample(args, 'image', image_paths, index, entry)
                else:   # for pure text
                    content = {
                        "texts": entry[args.columns_messages],
                        "media": "text",
                    }
                    sample = {
                        "__key__": 'text_' + str(index),
                        "json": json.dumps(content).encode("utf-8"),
                    }
            shard_writer.write(sample)
    if args.media == "mix" or args.media == "video":
        write_config(EPath(args.output_dir).absolute(), args.media)

    print(f"Dataset successfully converted to wds")

def write_config(path: EPath, media: str=None):
    """ Write config to path """
    (path / MAIN_FOLDER_NAME).mkdir()
    all_tars = list(path.glob("**/*.tar")) + list(path.glob("**/*.tgz"))
    all_tars = [str(p.relative_to(path)) for p in sorted(all_tars)]
    class_type = "MultiMixQASample" if media == 'mix' else "MultiVidQASample"
    dataset_definition = {
        "sample_type": {
            "__module__": "aiak_training_llm.data.multimodal",
            "__class__": class_type,
        },
        "part_filter": "sample_loader.py:part_filter",
        "sample_loader": "sample_loader.py:sample_loader"
    }
    with (path / MAIN_FOLDER_NAME / "dataset.yaml").open("w") as f:
        yaml.dump(dataset_definition, f, sort_keys=False)
    with (path / MAIN_FOLDER_NAME / "sample_loader.py").open("w") as f:
        f.write(sample_loader_template(media))

    BaseWebdatasetFactory.prepare_dataset(
        path,
        all_tars,
        split_parts_ratio=[("train", 1.0), ("val", 0), ("test", 0)],
        tar_index_only=False,
        workers=96,
    )

def _add_arguments(parser: argparse.ArgumentParser):
    """Add arguments"""
    group = parser.add_argument_group(title='wds')
    group.add_argument('--output_dir', type=str, required=True, help='Output directory')
    group.add_argument('--json_file', type=str, required=True, help='Json file')
    group.add_argument('--image_dir', type=str, required=False, help='Image directory')
    group.add_argument('--video_dir', type=str, required=False, help='Video directory')
    group.add_argument('--maxcount', type=int, default=10000, help='Number of samples per shard')
    group.add_argument('--maxsize', type=int, default=3000000000, help='Maximum size of each shard')
    group.add_argument('--media', type=str, choices=["mix", "image", "video"], default="mix", help='Media type')
    group.add_argument('--columns_messages', type=str, default="messages", help='Column name for messages')

    return parser


def parse_args():
    """arguments"""
    parser = argparse.ArgumentParser()
    _add_arguments(parser)
    args = parser.parse_args()

    return args


def main():
    """main function"""
    args = parse_args()
    convert_to_wds(args)


if __name__ == '__main__':
    main()