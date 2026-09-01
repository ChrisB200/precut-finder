def format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    seconds = seconds % 60

    return f"{minutes}:{seconds:05.2f}"
