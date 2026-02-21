import json


def get_path_value(root: dict, path: str) -> object:
    node: object = root
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_path_value(root: dict, path: str, value: object) -> None:
    parts = path.split(".")
    node = root
    for key in parts[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[parts[-1]] = value


def coerce_field_value(field_type: str, value: object) -> object:
    if field_type == "integer":
        return int(str(value)) if value is not None and value != "" else 0
    if field_type == "number":
        return float(str(value)) if value is not None and value != "" else 0.0
    if field_type == "boolean":
        return bool(value)
    if field_type == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("must be a JSON object")
            return parsed
        raise ValueError("must be object")
    if field_type == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("must be a JSON array")
            return [str(v).strip() for v in parsed if str(v).strip()]
        raise ValueError("must be list")
    if field_type == "map_integer":
        if not isinstance(value, dict):
            raise ValueError("must be object")
        map_int_out: dict[str, int] = {}
        for key, raw in value.items():
            k = str(key).strip()
            if not k:
                continue
            map_int_out[k] = int(str(raw))
        return map_int_out
    if field_type == "map_list":
        if not isinstance(value, dict):
            raise ValueError("must be object")
        map_list_out: dict[str, list[str]] = {}
        for key, raw in value.items():
            k = str(key).strip()
            if not k:
                continue
            if isinstance(raw, list):
                map_list_out[k] = [str(v).strip() for v in raw if str(v).strip()]
            elif isinstance(raw, str):
                map_list_out[k] = [v.strip() for v in raw.split(",") if v.strip()]
            else:
                raise ValueError("map_list values must be list or comma-separated string")
        return map_list_out
    if field_type == "prompt_override":
        if not isinstance(value, dict):
            raise ValueError("must be object")
        return {
            "prefix": str(value.get("prefix") or ""),
            "suffix": str(value.get("suffix") or ""),
            "template": str(value.get("template") or ""),
        }
    return "" if value is None else str(value)
