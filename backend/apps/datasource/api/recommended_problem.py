from fastapi import APIRouter

from apps.datasource.crud.datasource import update_ds_recommended_config
from apps.datasource.crud.recommended_problem import get_datasource_recommended, \
    save_recommended_problem, get_datasource_recommended_base
from apps.datasource.models.datasource import RecommendedProblemBase
from apps.swagger.i18n import PLACEHOLDER_PREFIX
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.audit.models.log_model import OperationType, OperationModules
from common.audit.schemas.logger_decorator import LogConfig, system_log
from common.core.deps import SessionDep, CurrentUser

router = APIRouter(tags=["recommended problem"], prefix="/recommended_problem")


@router.get("/get_datasource_recommended/{ds_id}", response_model=None, summary=f"{PLACEHOLDER_PREFIX}rp_get")
@require_permissions(permission=SqlbotPermission(type='ds', keyExpression="ds_id"))
async def datasource_recommended(session: SessionDep, user: CurrentUser, ds_id: int):
    return get_datasource_recommended(session, ds_id)


@router.get("/get_datasource_recommended_base/{ds_id}", response_model=None, summary=f"{PLACEHOLDER_PREFIX}rp_base")
@require_permissions(permission=SqlbotPermission(type='ds', keyExpression="ds_id"))
async def datasource_recommended_base(session: SessionDep, user: CurrentUser, ds_id: int):
    return get_datasource_recommended_base(session, ds_id)


@router.post("/save_recommended_problem", response_model=None, summary=f"{PLACEHOLDER_PREFIX}rp_save")
@require_permissions(permission=SqlbotPermission(type='ds', keyExpression="data_info.datasource_id"))
@system_log(
    LogConfig(operation_type=OperationType.UPDATE, module=OperationModules.DATASOURCE,
              resource_id_expr="data_info.datasource_id"))
async def datasource_recommended_save(session: SessionDep, user: CurrentUser, data_info: RecommendedProblemBase):
    update_ds_recommended_config(session, data_info.datasource_id, data_info.recommended_config)
    return save_recommended_problem(session, user, data_info)
