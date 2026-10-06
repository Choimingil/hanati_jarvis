import random
from datetime import datetime


services = [
    "auth-service",
    "payment-service",
    "order-service"
]


normal_logs = [
    "User login success",
    "Payment completed",
    "Order created"
]


error_logs = [
    "Database connection failed",
    "Timeout occurred",
    "Payment gateway error"
]



def generate_log():

    level = random.choice(
        ["INFO", "INFO", "WARN", "ERROR"]
    )


    if level == "ERROR":

        message = random.choice(error_logs)

    else:

        message = random.choice(normal_logs)



    return {

        "timestamp": datetime.now(),

        "service":
            random.choice(services),

        "level":
            level,

        "message":
            message,

        "host":
            "server01",

        "environment":
            "production"

    }