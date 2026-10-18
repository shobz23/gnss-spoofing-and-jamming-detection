"""Replay recorded receiver observations into the prediction API, in bounded batches.

Use a model trained on compatible receiver features. Input remains an offline replay;
the sensor name is prefixed with Replay so incidents cannot imply a live receiver.
"""
import argparse
import json
import os
import time
import urllib.request

import pandas as pd
from gnss_sentinel.datasets import SPOOF_FEATURES, validate_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("--model-id",required=True)
    parser.add_argument("--url",default="http://127.0.0.1:8765")
    parser.add_argument("--sensor",default="receiver-01")
    parser.add_argument("--batch-size",type=int,default=32)
    parser.add_argument("--interval",type=float,default=1)
    parser.add_argument("--no-incidents",action="store_true")
    args=parser.parse_args()
    if not 1 <= args.batch_size <= 512 or args.interval < 0:
        parser.error("Batch size must be 1–512; interval cannot be negative.")
    for batch in pd.read_csv(args.csv,chunksize=args.batch_size):
        frame=validate_frame(batch,require_labels=False)
        payload={"model_id":args.model_id,"rows":frame[SPOOF_FEATURES].to_dict(orient="records"),
                 "sensor":("Replay / "+args.sensor)[:100],"record_incident":not args.no_incidents}
        request=urllib.request.Request(args.url.rstrip('/')+'/api/predict',data=json.dumps(payload,allow_nan=False).encode(),
            headers={"Content-Type":"application/json","X-API-Key":os.getenv("SENTINEL_API_KEY","")},method="POST")
        with urllib.request.urlopen(request,timeout=60) as response:
            result=json.load(response)
        print(json.dumps({"observations":len(result["predictions"]),"incidents":len(result["incident_ids"]),
                          "labels":[r["label"] for r in result["predictions"]]}),flush=True)
        time.sleep(args.interval)


if __name__=='__main__':
    main()
