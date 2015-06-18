# -*- coding: utf-8 -*-

"""Including this module sets up a state change event subscription system
  that dispatches incoming http requests to registered subscribers for a
  given context and state.

  You can then register event handlers for a given resource and request
  param value:

      # Subscribe to a state change.
      config.add_engine_subscriber(IFoo, 'state:DECLINED', notify_user)

      # Subscribe to an action happening.
      config.add_engine_subscriber(IFoo, 'action:DECLINE', notify_user)

  And dispatch to them using `torque.engine.changed(context, event)`.
  Plus it provides `request.activity_event` to lookup an activity event
  identified by the `event_id` request param.
"""

__all__ = [
    'AddEngineSubscriber',
    'GetActivityEvent',
    'ParamAwareSubscriber',
    'StateChangeHandler',
    'operation_config',
]

import logging
logger = logging.getLogger(__name__)

import zope.interface

from . import repo

class operation_config(object):
    """Decorator that gives a handler function an operation name."""

    def __init__(self, operation):
        self.op = operation

    def __call__(self, wrapped, *a, **kw):
        def func(*args):
            expanded_args = args + tuple([self.op])
            return wrapped(*expanded_args)
        func.op = self.op
        return func

class StateChangeHandler(object):
    """Dispatch state changed events to registered subscribers."""

    def __init__(self, **kwargs):
        self.providedBy = kwargs.get('providedBy', zope.interface.providedBy)

    def __call__(self, request):
        """Log and call."""

        # Unpack.
        context = request.context
        event = request.activity_event
        registry = request.registry
        subscriptions = registry.adapters.subscriptions
        providedBy = self.providedBy

        # Dispatch.
        results = []
        for handler in subscriptions([providedBy(context)], None):
            # Note that we pass through the args as a single tuple
            # as the Pyramid events machinery expects a single value.
            combined_args = (request, context, event)
            results.append(handler(combined_args))
        return {'handlers': [item for item in results if item is not None]}

class ParamAwareSubscriber(object):
    """Wrap an activity event handler with a callable that only calls the
      handler if a named request param matches.
    """

    def __init__(self, param, value, handler):
        self.param = param
        self.value = value
        self.handler = handler

    def __call__(self, combined_args):
        """Validate that the request param matches and, if so, call the
          handler function.
        """

        # Unpack the combined args into `request, *args`.
        request = combined_args[0]
        args = combined_args[1:]

        # Validate the state param matches.
        param_value = request.json.get(self.param, None)
        if param_value != self.value:
            return None

        # If so, call the handler.
        return self.handler(request, *args)

class AddEngineSubscriber(object):
    """Register a ``handler`` function for one or more namespaced events."""

    def __init__(self, **kwargs):
        self.wrapper_cls = kwargs.get('wrapper_cls', ParamAwareSubscriber)

    def __call__(self, config, context, namespaced_events, handler):
        """Subscribe a handler for each event."""

        # Make sure we have a list.
        if not hasattr(namespaced_events, '__iter__'):
            namespaced_events = (namespaced_events,)

        # For each event, add a subscriber.
        for value in namespaced_events:
            # Split e.g.: `'state:FOO'` into `('state', 'FOO')`.
            param_name = value.split(':')[0]
            # Add a request param aware subscriber.
            subscriber = self.wrapper_cls(param_name, value, handler)
            config.add_subscriber(subscriber, context)

class GetActivityEvent(object):
    """Request method to lookup ActivityEvent instance from the value in the
      ``event_id`` request param, falling back on the instance related to
      the context's work status.
    """

    def __init__(self, **kwargs):
        self.lookup = kwargs.get('lookup', repo.LookupActivityEvent())

    def __call__(self, request):
        candidate = request.json.get('event_id', None)
        try:
            event_id = int(candidate)
        except (TypeError, ValueError):
            pass
        else: # Lookup.
            event = self.lookup(event_id)
            if event:
                return event
        # Fallback.
        if request.context:
            status = getattr(request.context, 'work_status', None)
            if status:
                return status.event

class IncludeMe(object):
    """Set up the state change event subscription system and provide an
      ``add_engine_subscriber`` directive.
    """

    def __init__(self, **kwargs):
        self.handler = kwargs.get('handler', StateChangeHandler())
        self.add_subscriber = kwargs.get('add_subscriber', AddEngineSubscriber())
        self.get_activity_event = kwargs.get('get_activity_event',
                GetActivityEvent().__call__)

    def __call__(self, config):
        """Handle `/events` requests and provide subscription directive."""

        # Unpack.
        handler = self.handler
        add_subscriber = self.add_subscriber
        get_activity_event = self.get_activity_event

        # Handle `POST {state, event_id} /events/:tablename/:id`.
        config.add_route('events', '/events/*traverse')
        config.add_view(handler, renderer='json', request_method='POST',
                route_name='events')

        # Provide `add_state_change_subscriber` directive.
        config.add_directive('add_engine_subscriber', add_subscriber)

        # Provide `request.activity_event`.
        config.add_request_method(get_activity_event, 'activity_event', reify=True)

includeme = IncludeMe().__call__
