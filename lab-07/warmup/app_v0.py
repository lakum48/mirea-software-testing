from itertools import count

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
ITEMS: dict[int, dict] = {}
sequence = count(1)


class ItemIn(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


@app.post("/items", status_code=201)
def create_item(item: ItemIn) -> dict:
    item_id = next(sequence)
    ITEMS[item_id] = item.model_dump()
    return {"id": item_id, **ITEMS[item_id]}


@app.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int) -> Response:
    if item_id not in ITEMS:
        raise HTTPException(404, "Not found")
    del ITEMS[item_id]
    return Response(status_code=204)
