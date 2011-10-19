

def includeme(config):
    config.add_route('heartbeat', '/__heartbeat__')
    config.scan('mozsvc.views')
