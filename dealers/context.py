from .models import Group


def get_current_group(request):
    active_groups = Group.objects.filter(active=True).order_by("id")
    group_id = request.session.get("current_group_id")
    group = active_groups.filter(pk=group_id).first() if group_id else None
    if group is None:
        group = active_groups.first()
        if group:
            request.session["current_group_id"] = group.pk
    return group


def group_context(request):
    current_group = get_current_group(request)
    return {
        "current_group": current_group,
        "active_groups": Group.objects.filter(active=True).order_by("id"),
        "current_group_is_empty": bool(current_group and current_group.is_empty),
    }
