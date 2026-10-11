from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.deps import require_admin

router = APIRouter(tags=["admin-help"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/admin-help", response_class=HTMLResponse)
def admin_help(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse(request, "admin_help.html", {"user": admin})
