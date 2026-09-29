# RunPod serverless handler for NetSolP-1.0.
#
# Example request:
# {"input": {"fasta": ">seq1\nMKT...", "model_type": "Distilled", "prediction_type": "SU"}}
# or
# {"input": {"sequences": [{"id": "seq1", "sequence": "MKT..."}], ...}}
import argparse
import glob
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

import pandas as pd
import runpod

from predict import get_preds, get_preds_distilled

APP_MODELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
VOLUME_MODELS_PATH = "/runpod-volume/models"

MODEL_TYPES = ["ESM12", "ESM1b", "Both", "Distilled"]
PREDICTION_TYPES = ["S", "U", "SU"]


def resolve_models_path():
    """MODELS_PATH env var > network volume > models bundled in the image."""
    if os.environ.get("MODELS_PATH"):
        return os.environ["MODELS_PATH"]
    if glob.glob(os.path.join(VOLUME_MODELS_PATH, "*.onnx")):
        return VOLUME_MODELS_PATH
    return APP_MODELS_PATH


def download_models(url, dest):
    """Download a .zip / .tar.gz archive of the ONNX models and put every .onnx file in dest."""
    print(f"Downloading models from {url}")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "models_archive")
        urllib.request.urlretrieve(url, archive)
        extract_dir = os.path.join(tmp, "extracted")
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                z.extractall(extract_dir)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                t.extractall(extract_dir)
        else:
            raise RuntimeError("MODELS_URL must point to a .zip or .tar(.gz) archive")
        os.makedirs(dest, exist_ok=True)
        for f in glob.glob(os.path.join(extract_dir, "**", "*.onnx"), recursive=True):
            shutil.move(f, os.path.join(dest, os.path.basename(f)))


MODELS_PATH = resolve_models_path()
if os.environ.get("MODELS_URL") and not glob.glob(os.path.join(MODELS_PATH, "*.onnx")):
    download_models(os.environ["MODELS_URL"], MODELS_PATH)
# The alphabet ships with the repo; make sure it is next to the models.
if not os.path.exists(os.path.join(MODELS_PATH, "ESM12_alphabet.pkl")):
    try:
        shutil.copy(os.path.join(APP_MODELS_PATH, "ESM12_alphabet.pkl"), MODELS_PATH)
    except OSError as e:
        print(f"Could not copy ESM12_alphabet.pkl into {MODELS_PATH}: {e}")
print(f"Using models from {MODELS_PATH}")


def required_models(model_type, prediction_type):
    names = []
    for p in prediction_type:
        target = "Solubility" if p == "S" else "Usability"
        if model_type == "Distilled":
            names.append(f"{target}_ESM1b_distilled_quantized.onnx")
        else:
            mts = ["ESM12", "ESM1b"] if model_type == "Both" else [model_type]
            names += [f"{target}_{mt}_{i}_quantized.onnx" for mt in mts for i in range(5)]
    return names


def to_fasta(job_input):
    if job_input.get("fasta"):
        return job_input["fasta"]
    seqs = job_input.get("sequences")
    if isinstance(seqs, dict):
        seqs = [{"id": k, "sequence": v} for k, v in seqs.items()]
    if not seqs:
        return None
    return "\n".join(f">{s.get('id', f'seq{i}')}\n{s['sequence']}" for i, s in enumerate(seqs))


def handler(job):
    job_input = job["input"]
    model_type = job_input.get("model_type", "Distilled")
    prediction_type = job_input.get("prediction_type", "S")

    if model_type not in MODEL_TYPES:
        return {"error": f"model_type must be one of {MODEL_TYPES}"}
    if prediction_type not in PREDICTION_TYPES:
        return {"error": f"prediction_type must be one of {PREDICTION_TYPES}"}
    fasta = to_fasta(job_input)
    if not fasta:
        return {"error": "Provide 'fasta' (FASTA text) or 'sequences' ([{id, sequence}] or {id: sequence})"}

    missing = [m for m in required_models(model_type, prediction_type)
               if not os.path.exists(os.path.join(MODELS_PATH, m))]
    if missing:
        return {"error": f"Missing model files in {MODELS_PATH}: {missing}"}

    with tempfile.TemporaryDirectory() as tmp:
        fasta_path = os.path.join(tmp, "input.fasta")
        output_path = os.path.join(tmp, "preds.csv")
        with open(fasta_path, "w") as f:
            f.write(fasta)
        args = argparse.Namespace(
            FASTA_PATH=fasta_path,
            OUTPUT_PATH=output_path,
            MODELS_PATH=MODELS_PATH,
            NUM_THREADS=int(os.environ.get("NUM_THREADS", os.cpu_count())),
            MODEL_TYPE=model_type,
            PREDICTION_TYPE=prediction_type,
        )
        if model_type == "Distilled":
            get_preds_distilled(args)
        else:
            get_preds(args)
        preds = pd.read_csv(output_path)

    return {"predictions": preds.to_dict(orient="records")}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
