import uvicorn

from vlrgg import config

if __name__ == "__main__":
    uvicorn.run("vlrgg.app:app", host=config.HOST, port=config.PORT, proxy_headers=True, forwarded_allow_ips="*")
