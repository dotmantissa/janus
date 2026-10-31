# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *

class Compatibility(gl.Contract):
    owner: Address
    now: str
    def __init__(self):
        self.owner = gl.message.sender_address
        self.now = str(gl.message_raw.get("datetime", ""))
    @gl.public.view
    def inspect(self) -> dict:
        return {"owner": self.owner.as_hex, "time": self.now}
