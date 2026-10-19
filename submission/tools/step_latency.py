import time,statistics
from app.config import Settings
from app.main import build_engine
e=build_engine(Settings())
for _ in range(60): e.step_sample()
ts=[]
for _ in range(200):
    t=time.perf_counter(); e.step_sample(); ts.append((time.perf_counter()-t)*1000)
ts.sort(); print("median ms",round(statistics.median(ts),1),"p95",round(ts[int(.95*len(ts))],1),"max",round(ts[-1],1))
import torch; print("threads",torch.get_num_threads())
