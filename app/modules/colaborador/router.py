from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def test_route():
    return {"status": "ok", "module": "colaborador"}
