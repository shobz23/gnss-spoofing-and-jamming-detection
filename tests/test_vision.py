"""Opt-in CPU smoke test; no downloads or real dataset required."""
import os
from pathlib import Path
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SENTINEL_TEST_VISION") != "1", reason="Set SENTINEL_TEST_VISION=1 with the vision extra installed.")


def test_vision_training_checkpoint_reload_and_inference(tmp_path):
    import torch
    from PIL import Image
    from gnss_sentinel.vision import train_images, predict_image
    torch.set_num_threads(2)
    rng=np.random.default_rng(42)
    root=tmp_path/"images"
    for split, count in [("train",4),("val",2),("test",2)]:
        for label in ["clean","chirp"]:
            folder=root/split/label
            folder.mkdir(parents=True)
            for index in range(count):
                pixels=rng.integers(0,256,(128,128,3),dtype=np.uint8)
                Image.fromarray(pixels).save(folder/f"{index}.png")
    report=train_images(root,tmp_path/"output",epochs=1,batch_size=4)
    assert report["split_sizes"] == {"train":8,"val":4,"test":4}
    assert sum(map(sum,report["confusion_matrix"]))==4
    result=predict_image(tmp_path/"output/best.pt",root/"test/clean/0.png")
    assert sum(result["probabilities"].values()) == pytest.approx(1,abs=1e-6)
    assert result["label"] in {"chirp","clean"}
    import shutil
    shutil.copyfile(root/"train/clean/0.png",root/"test/clean/0.png")
    with pytest.raises(ValueError,match="Duplicate image"):
        train_images(root,tmp_path/"should-not-exist",epochs=1)
