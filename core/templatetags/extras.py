from django import template

register = template.Library()

@register.filter
def index(sequence, position):
    """
    Returns item at given index from a list/tuple.
    Usage: {{ my_list|index:0 }}
    """
    try:
        return sequence[position]
    except (IndexError, TypeError):
        return None

@register.filter
def dict_key(dictionary, key):
    """
    Returns dict value for given key.
    Usage: {{ my_dict|dict_key:key }}
    """
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def get_item(dictionary, key):
    """
    Alias for dict_key.
    Usage: {{ my_dict|get_item:key }}
    """
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def has_role(user, role_names):
    """
    Checks if a user belongs to any of the specified roles (comma-separated).
    Superusers bypass role checks.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    roles = [r.strip() for r in role_names.split(',')]
    try:
        return user.profile.role in roles
    except Exception:
        return False


@register.filter
def has_perm(user, permission_name):
    """
    Checks if a user has a specific fine-grained scheduling permission.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    
    # Mapping of permissions to roles
    permissions_map = {
        'publish_schedule': ['SCHEDULER', 'ACADEMIC_MANAGER', 'BRANCH_MANAGER'],
        'override_locks': ['ACADEMIC_MANAGER', 'BRANCH_MANAGER'],
        'bulk_edit': ['SCHEDULER', 'ACADEMIC_MANAGER', 'BRANCH_MANAGER'],
        'approve_changes': ['ACADEMIC_MANAGER', 'BRANCH_MANAGER'],
        'view_audit': ['ACADEMIC_MANAGER', 'BRANCH_MANAGER', 'AUDITOR'],
    }
    
    allowed_roles = permissions_map.get(permission_name, [])
    try:
        return user.profile.role in allowed_roles
    except Exception:
        return False

