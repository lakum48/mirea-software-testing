import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import Float, Integer, String, create_engine, event, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Price = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Stock = Annotated[int, Field(ge=0, le=25, strict=True)]
Currency = Literal["USD", "EUR"]


class Base(DeclarativeBase):
    pass


class Bike(Base):
    __tablename__ = "bikes"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    price: Mapped[float] = mapped_column(Float)
    in_stock: Mapped[int] = mapped_column(Integer)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateBike(Body):
    name: Name
    price: Price
    in_stock: Stock = 0


class ReplaceBike(CreateBike):
    in_stock: Stock


class ReadBike(ReplaceBike):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ChangeBike(Body):
    name: Name | None = None
    price: Price | None = None
    in_stock: Stock | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "ChangeBike":
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Требуется хотя бы одно поле с заданным значением")
        return self


class Delta(Body):
    delta: Annotated[int, Field(strict=True)]

    @model_validator(mode="after")
    def check_nonzero(self) -> "Delta":
        if self.delta == 0:
            raise ValueError("Изменение должно быть ненулевым")
        return self


class Login(Body):
    username: str
    password: str


@event.listens_for(Engine, "connect")
def add_casefold(connection, _record) -> None:
    connection.create_function("casefold", 1, str.casefold, deterministic=True)


engine = create_engine(os.getenv("BIKES_DB_URL", "sqlite:///bikes.db"), connect_args={"check_same_thread": False})
tokens: dict[str, str] = {}
tokens_lock = Lock()


@asynccontextmanager
async def lifespan(application: FastAPI):
    Base.metadata.create_all(engine)
    yield
    with tokens_lock:
        tokens.clear()


app = FastAPI(title="Прокат велосипедов", lifespan=lifespan)


def db_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


DB = Annotated[Session, Depends(db_session)]


def role(authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    with tokens_lock:
        value = tokens.get(token) if scheme.lower() == "bearer" else None
    if not value:
        raise HTTPException(401, "Требуется действительный токен")
    return value


def admin(current: Annotated[str, Depends(role)]) -> None:
    if current != "admin":
        raise HTTPException(403, "Требуется роль admin")


read_access = [Depends(role)]
write_access = [Depends(admin)]


def rate_source(currency: Currency) -> float:
    endpoint = os.getenv("BIKES_RATES_URL")
    if not endpoint:
        raise HTTPException(502, "Адрес сервиса курсов не настроен")
    try:
        response = httpx.get(endpoint, timeout=3)
        response.raise_for_status()
        rate = float(response.json()["rates"][currency])
        if not 0 < rate < float("inf"):
            raise ValueError("Недопустимый курс")
        return rate
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
        raise HTTPException(502, "Сервис курсов недоступен") from error


def get_rate_source() -> Callable[[Currency], float]:
    return rate_source


def find_bike(session: Session, bike_id: int) -> Bike:
    bike = session.get(Bike, bike_id)
    if bike is None:
        raise HTTPException(404, "Велосипед не найден")
    return bike


def save(session: Session, bike: Bike) -> Bike:
    try:
        session.add(bike)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Название уже занято") from error
    session.refresh(bike)
    return bike


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
def login(body: Login) -> dict[str, str]:
    passwords = {"admin": os.getenv("BIKES_ADMIN_PASSWORD"), "viewer": os.getenv("BIKES_VIEWER_PASSWORD")}
    expected = passwords.get(body.username)
    if not expected or not secrets.compare_digest(expected.encode(), body.password.encode()):
        raise HTTPException(401, "Неверные учётные данные")
    token = secrets.token_urlsafe(32)
    with tokens_lock:
        tokens[token] = body.username
    return {"access_token": token, "token_type": "bearer"}


@app.post("/bikes", status_code=201, response_model=ReadBike, dependencies=write_access)
def create_bike(body: CreateBike, session: DB) -> Bike:
    return save(session, Bike(**body.model_dump()))


@app.get("/bikes", response_model=list[ReadBike], dependencies=read_access)
def list_bikes(
    session: DB,
    q: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Bike]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(422, "Минимальная цена выше максимальной")
    rows = select(Bike).order_by(Bike.id)
    if q:
        # SQLite lower() по умолчанию работает только для ASCII. casefold учитывает кириллицу.
        rows = rows.where(func.instr(func.casefold(Bike.name), q.casefold()) > 0)
    if min_price is not None:
        rows = rows.where(Bike.price >= min_price)
    if max_price is not None:
        rows = rows.where(Bike.price <= max_price)
    return list(session.scalars(rows.offset(offset).limit(limit)))


@app.get("/bikes/{bike_id}", response_model=ReadBike, dependencies=read_access)
def get_bike(bike_id: int, session: DB) -> Bike:
    return find_bike(session, bike_id)


@app.put("/bikes/{bike_id}", response_model=ReadBike, dependencies=write_access)
def replace_bike(bike_id: int, body: ReplaceBike, session: DB) -> Bike:
    bike = find_bike(session, bike_id)
    for key, value in body.model_dump().items():
        setattr(bike, key, value)
    return save(session, bike)


@app.patch("/bikes/{bike_id}", response_model=ReadBike, dependencies=write_access)
def change_bike(bike_id: int, body: ChangeBike, session: DB) -> Bike:
    bike = find_bike(session, bike_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(bike, key, value)
    return save(session, bike)


@app.delete("/bikes/{bike_id}", status_code=204, dependencies=write_access)
def delete_bike(bike_id: int, session: DB) -> Response:
    session.delete(find_bike(session, bike_id))
    session.commit()
    return Response(status_code=204)


@app.post("/bikes/{bike_id}/stock", response_model=ReadBike, dependencies=write_access)
def change_stock(bike_id: int, body: Delta, session: DB) -> Bike:
    if abs(body.delta) > 25:
        find_bike(session, bike_id)
        raise HTTPException(409, "Остаток вне диапазона")
    new_value = Bike.in_stock + body.delta
    changed = session.execute(
        update(Bike).where(Bike.id == bike_id, new_value.between(0, 25)).values(in_stock=new_value),
    )
    if not changed.rowcount:
        find_bike(session, bike_id)
        raise HTTPException(409, "Остаток вне диапазона")
    session.commit()
    return find_bike(session, bike_id)


@app.get("/bikes/{bike_id}/price", dependencies=read_access)
def converted_price(
    bike_id: int,
    currency: Currency,
    session: DB,
    provider: Annotated[Callable[[Currency], float], Depends(get_rate_source)],
) -> dict[str, float | str]:
    bike = find_bike(session, bike_id)
    return {"currency": currency, "price": round(bike.price * provider(currency), 2)}
