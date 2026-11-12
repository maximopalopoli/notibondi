import sys
from pathlib import Path

from google.transit import gtfs_realtime_pb2

feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(Path(sys.argv[1]).read_bytes())
print(f"{len(feed.entity)} entities, feed timestamp {feed.header.timestamp}")
