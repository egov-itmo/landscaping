"""
get_plants endpoint is defined here.
"""
from io import BytesIO

from fastapi import Depends, File, UploadFile
from loguru import logger
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette import status

from plants_api.db.connection import get_connection
from plants_api.dto.users import User
from plants_api.exceptions.logic.photos import PhotoOpenError
from plants_api.logic.update.photos import set_photo_to_plant
from plants_api.schemas.basic_responses import OkResponse
from plants_api.utils.dependencies import user_dependency

from .router import update_router


@update_router.post(
    "/plant/{plant_id}/photo",
    response_model=OkResponse,
    status_code=status.HTTP_200_OK,
)
async def set_plant_photo(
    plant_id: int,
    _user: User = Depends(user_dependency),
    photo_data: UploadFile = File(...),
    connection: AsyncConnection = Depends(get_connection),
) -> OkResponse:
    """
    Set given plant photo and create a thumbnail.
    """
    try:
        with BytesIO(await photo_data.read()) as buffer:
            photo = Image.open(buffer)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Error on updating photo for plant with id={}: {!r}", plant_id, exc)
        raise PhotoOpenError(plant_id) from exc
    await set_photo_to_plant(connection, plant_id, photo)
    return OkResponse()
