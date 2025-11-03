import time
from zheliku_tool import TimeLogger, time_log

with TimeLogger():
    time.sleep(1)


with time_log():
    time.sleep(1.5)

@TimeLogger()
def example_function():
    time.sleep(0.5)
    return "Function complete"

result = example_function()
