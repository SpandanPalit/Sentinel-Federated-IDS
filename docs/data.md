# Sentinel data preparation

Prepare the demo locally from the original captures. The output consists of `state/prepared/manifest.json` and one compressed NumPy partition per device. See [dataset attribution](../data/NOTICE.md).

## Reproduce from the original captures

1. Select **Download (1.7 GB)** on the [UCI N-BaIoT dataset page](https://doi.org/10.24432/C5RC8J). Extract the ZIP to `data/raw`.
2. Inside each desired device folder, extract the attack RAR files with a RAR-capable extractor such as 7-Zip. Keep the CSVs directly inside folders named `gafgyt_attacks` and, when supplied, `mirai_attacks`. Check for and flatten an extra nested directory level. Keep each device's `benign_traffic.csv` in its device folder. The directory containing the device folders is the `--raw` argument.
3. Use the following command in PowerShell, Bash or another shell. It applies the same bounded prefix profile to the available original captures. The default upper limit is three clients. To include up to nine, pass `--clients 9` and use a fresh state directory for the new experiment.

```text
python -m sentinel.prepare --raw "data/raw"
```

```text
data/raw/
  Danmini_Doorbell/
    benign_traffic.csv
    gafgyt_attacks/{combo,junk,scan,tcp,udp}.csv
    mirai_attacks/{ack,scan,syn,udp,udpplain}.csv
  Ecobee_Thermostat/...
  Ennio_Doorbell/...
```

An existing directory can be used directly, including a path outside this checkout. A repeat preparation reuses parsed capture prefixes in `state/.prepare-cache`. Cache keys for local inputs include path, size and modification time. The program stages new outputs until it has validated every partition, verifies existing partitions on a repeated run and refuses to overwrite a different cohort. Use `--output PATH/prepared` for a different dataset. Full source files, caches and generated state are Git-ignored.

## How rows reach each split

The consumer validates the canonical 115 column names and their order, parses only finite numeric values, and derives the binary label from the file's role. Device names, file paths and attack names are retained solely as provenance. The selection is deterministic and intentionally small. Each benign prefix contains up to 1,792 rows and each attack prefix contains up to 256. This convenience sample emphasizes the start of captures. Its evaluation describes those records and devices; it cannot establish generalization to the full capture timeline, new networks or new devices.

For each device, alphabetically sorted attack CSV paths form capture groups. With at least three files, the last two fifth-sized groups (rounded, at least one file each) become validation and test. The earlier files supply training. Every selected row from a given attack file stays in its assigned split. Separate files are the best available grouping here; the source does not guarantee statistical independence between files.

For a single ordered source, Sentinel removes two gaps before constructing batches. It reserves one sixth of the usable records for validation and one sixth for test, leaving the earlier records for training. With a full benign prefix this gives rows `[0,1024)` for training, `[1152,1408)` for validation, and `[1536,1792)` for test. The gaps are 128 observations each. On short captures each gap is capped at one eighth of the input (minimum one). A gap measured in records cannot prove that the extractor's time windows have stopped overlapping. With two source files of a class, the first supplies training and the other provides separated validation and test blocks. Inputs too small to retain both classes produce an error.

Before scaling, SHA-256 fingerprints of the 115 parsed double-precision feature values are compared across **all** selected devices. Signed zero is canonicalized. Training takes precedence over validation, and validation over test. Every row matching an earlier split is removed from the later split regardless of its label. Repeated observations within the same split retain their empirical frequency. The manifest records each source path, half-open zero-based input range, block fingerprint, removal count, post-audit class counts and device-to-client mapping.

| Client | Device | Train benign / attack | Validation benign / attack | Test benign / attack |
|---|---|---:|---:|---:|
| 1 | Danmini Doorbell | 1,024 / 1,536 | 256 / 512 | 256 / 512 |
| 2 | Ecobee Thermostat | 1,024 / 1,536 | 256 / 512 | 256 / 512 |
| 3 | Ennio Doorbell | 1,024 / 768 | 256 / 248 | 256 / 242 |

The verified demo profile lost eight validation rows and fourteen test rows to cross-split overlap. It retains 6,912 training, 2,040 validation and 2,034 reserved test records. A separate comparison of the final float32 feature vectors across all clients found zero matches between any pair of splits in this profile. Predicting the training majority (attack) on every validation example gives 1,272 correct predictions out of 2,040, or 62.3529% accuracy.

Each client computes a per-feature population mean and standard deviation from its retained **training** features. It saves both arrays locally, replaces a zero scale with one and clips standardized values to ±12 before conversion to float32. Clipping bounds extreme traffic statistics. Local scaling represents each device relative to its own traffic distribution without exchanging its data statistics for training. A new device would need a calibrated local scaler. Validation, test and prediction all reuse the corresponding device's training scaler. The central model weights alone do not specify this transformation.

## Predict from a saved round

After a run, replace `RUN_ID` with its actual ID. Supply a CSV with the original ordered feature header from the same device. The CLI checks the saved checkpoint and client partition digests against the run, applies the local scaler, and returns the argmax prediction for each requested row. Zero means benign and one means attack. A small prefix copied from the original capture is suitable for demonstrating inference.

```text
python -m sentinel.predict --run RUN_ID --round 1 --client 1 --csv "data/raw/Danmini_Doorbell/benign_traffic.csv" --limit 3
```
