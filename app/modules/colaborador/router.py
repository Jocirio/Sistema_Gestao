from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def listar_colaboradores():
    return {"mensagem": "Lista de colaboradores"}
