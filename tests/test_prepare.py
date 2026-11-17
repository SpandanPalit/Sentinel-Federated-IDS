import io

import numpy as np
import pytest

from sentinel.prepare import FEATURES, prepare, read_capture, transform


def test_schema_and_nonfinite_rejected():
    header = ",".join(FEATURES)
    wrong = ",".join(FEATURES[::-1])
    row = ",".join(["1"] * 114 + ["inf"])
    for text, error in [
        (wrong + "\n", "column 1"),
        (header + "\n" + row + "\n", "line 2"),
    ]:
        with pytest.raises(ValueError, match=error):
            read_capture(
                lambda _, content=text: io.BytesIO(content.encode()), "example.csv", 1
            )


def test_scaler_is_train_only_and_overlap_removed(tmp_path):
    # Two copies of one feature vector are deliberately placed in later split files.
    raw = tmp_path / "raw"
    source = raw / "Danmini_Doorbell"
    (source / "gafgyt_attacks").mkdir(parents=True)

    def write_capture(path, values):
        with path.open("w") as out:
            print(",".join(FEATURES), file=out)
            for v in values:
                print(",".join([str(v)] * 115), file=out)

    write_capture(source / "benign_traffic.csv", range(48))
    write_capture(source / "gafgyt_attacks/combo.csv", [500, 501])
    write_capture(source / "gafgyt_attacks/tcp.csv", [500, 502])
    write_capture(source / "gafgyt_attacks/udp.csv", [502, 503])
    output = tmp_path / "prepared"
    manifest = prepare(raw, output)
    client = manifest["clients"][0]
    assert client["cross_split_removed"] == {"train": 0, "validation": 1, "test": 1}
    assert prepare(raw, output) == manifest
    with np.load(output / "1.npz") as part:
        # Two gaps of six leave 24 train, six validation, six test benign rows.
        assert np.allclose(part["mean"], np.mean([*range(24), 500, 501]))
        assert np.allclose(
            part["X_test"][-1],
            transform(np.full(115, 503), part["mean"], part["scale"]),
        )
