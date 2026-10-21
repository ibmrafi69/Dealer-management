from .models import Group


def get_current_group(request):
    active_groups = Group.objects.filter(active=True).order_by("id")
    group_id = request.session.get("current_group_id")
    group = active_groups.filter(pk=group_id).first() if group_id else None
    if group is None:
        group = active_groups.first()
    return group


def group_context(request):
    active_groups = Group.objects.filter(active=True).order_by("id")
    group_id = request.session.get("current_group_id")
    current_group = active_groups.filter(pk=group_id).first() if group_id else None
    return {
        "current_group": current_group or active_groups.first(),
        "active_groups": active_groups,
        "current_group_is_empty": bool(current_group and current_group.is_empty),
    }
