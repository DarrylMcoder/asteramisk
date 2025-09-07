import aioari

from asteramisk.config import config

class AriClient:
    """ Basically a singleton wrapper for aioari.Client """
    _instance = None

    @classmethod
    async def create(cls, ari_host=config.ASTERISK_HOST, ari_port=config.ASTERISK_ARI_PORT, ari_user=config.ASTERISK_ARI_USER, ari_pass=config.ASTERISK_ARI_PASS):
        if not cls._instance:
            cls._instance = await aioari.connect(f"http://{ari_host}:{ari_port}", ari_user, ari_pass)
        return cls._instance

    @classmethod
    def is_instantiated(cls):
        return cls._instance is not None
