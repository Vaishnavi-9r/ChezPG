from pydantic import BaseModel, ConfigDict


class CityOut(BaseModel):
    id: int
    name: str
    state: str
    country: str

    model_config = ConfigDict(from_attributes=True)


class AreaOut(BaseModel):
    id: int
    city_id: int
    name: str

    model_config = ConfigDict(from_attributes=True)