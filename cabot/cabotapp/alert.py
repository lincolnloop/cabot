from os import environ as env
import ssl

from django.conf import settings
from django.core.mail import send_mail
from django.core.urlresolvers import reverse
from django.template import Context, Template

import irc.client, irc.connection
from twilio.rest import TwilioRestClient
from twilio import twiml
import requests
import logging

logger = logging.getLogger(__name__)

email_template = """Service {{ service.name }} {{ scheme }}://{{ host }}{% url 'service' pk=service.id %} {% if service.overall_status != service.PASSING_STATUS %}alerting with status: {{ service.overall_status }}{% else %}is back to normal{% endif %}.
{% if service.overall_status != service.PASSING_STATUS %}
CHECKS FAILING:{% for check in service.all_failing_checks %}
  FAILING - {{ check.name }} - Type: {{ check.check_category }} - Importance: {{ check.get_importance_display }}{% endfor %}
{% if service.all_passing_checks %}
Passing checks:{% for check in service.all_passing_checks %}
  PASSING - {{ check.name }} - Type: {{ check.check_category }} - Importance: {{ check.get_importance_display }}{% endfor %}
{% endif %}
{% endif %}
"""

chat_template = "Service {{ service.name }} {% if service.overall_status == service.PASSING_STATUS %}is back to normal{% else %}reporting {{ service.overall_status }} status{% endif %}: {{ scheme }}://{{ host }}{% url 'service' pk=service.id %}. {% if service.overall_status != service.PASSING_STATUS %}Checks failing:{% for check in service.all_failing_checks %} {{ check.name }}{% if check.last_result.error %} ({{ check.last_result.error|safe }}){% endif %}{% endfor %}{% endif %}{% if alert %}{% for alias in users %} @{{ alias }}{% endfor %}{% endif %}"

sms_template = "Service {{ service.name }} {% if service.overall_status == service.PASSING_STATUS %}is back to normal{% else %}reporting {{ service.overall_status }} status{% endif %}: {{ scheme }}://{{ host }}{% url 'service' pk=service.id %}"

telephone_template = "This is an urgent message from Arachnys monitoring. Service \"{{ service.name }}\" is erroring. Please check Cabot urgently."


def send_alert(service, duty_officers=None):
    users = service.users_to_notify.all()
    for service_name in ['email', 'hipchat', 'irc', 'sms', 'telephone']:
        if getattr(service, '{0}_alert'.format(service_name)):
            func = getattr(sys.modules[__name__],
                           'send_{0}_alert'.format(service_name))
            func(service, users, duty_officers)

def send_email_alert(service, users, duty_officers):
    emails = [u.email for u in users if u.email]
    if not emails:
        return
    c = Context({
        'service': service,
        'host': settings.WWW_HTTP_HOST,
        'scheme': settings.WWW_SCHEME
    })
    if service.overall_status != service.PASSING_STATUS:
        if service.overall_status == service.CRITICAL_STATUS:
            emails += [u.email for u in duty_officers]
        subject = '%s status for service: %s' % (
            service.overall_status, service.name)
    else:
        subject = 'Service back to normal: %s' % (service.name,)
    t = Template(email_template)
    send_mail(
        subject=subject,
        message=t.render(c),
        from_email='Cabot <%s>' % settings.CABOT_FROM_EMAIL,
        recipient_list=emails,
    )


def send_hipchat_alert(service, users, duty_officers):
    alert = True
    hipchat_aliases = [u.profile.hipchat_alias for u in users if hasattr(
        u, 'profile') and u.profile.hipchat_alias]
    if service.overall_status == service.WARNING_STATUS:
        alert = False  # Don't alert at all for WARNING
    if service.overall_status == service.ERROR_STATUS:
        if service.old_overall_status in (service.ERROR_STATUS, service.ERROR_STATUS):
            alert = False  # Don't alert repeatedly for ERROR
    if service.overall_status == service.PASSING_STATUS:
        color = 'green'
        if service.old_overall_status == service.WARNING_STATUS:
            alert = False  # Don't alert for recovery from WARNING status
    else:
        color = 'red'
        if service.overall_status == service.CRITICAL_STATUS:
            hipchat_aliases += [u.profile.hipchat_alias for u in duty_officers if hasattr(
                u, 'profile') and u.profile.hipchat_alias]
    c = Context({
        'service': service,
        'users': hipchat_aliases,
        'host': settings.WWW_HTTP_HOST,
        'scheme': settings.WWW_SCHEME,
        'alert': alert,
    })
    message = Template(hipchat_template).render(c)
    _send_hipchat_alert(message, color=color, sender='Cabot/%s' % service.name)



def _send_hipchat_alert(message, color='green', sender='Cabot'):
    room = settings.HIPCHAT_ALERT_ROOM
    api_key = settings.HIPCHAT_API_KEY
    url = settings.HIPCHAT_URL
    resp = requests.post(url + '?auth_token=' + api_key, data={
        'room_id': room,
        'from': sender[:15],
        'message': message,
        'notify': 1,
        'color': color,
        'message_format': 'text',
    })

def send_irc_alert(service, users, duty_officers):
    alert = True
    nicks = [u.profile.irc_nick for u in users if hasattr(
        u, 'profile') and u.profile.irc_nick]
    if service.overall_status == service.WARNING_STATUS:
        alert = False  # Don't alert at all for WARNING
    if service.overall_status == service.ERROR_STATUS:
        if service.old_overall_status in (service.ERROR_STATUS, service.ERROR_STATUS):
            alert = False  # Don't alert repeatedly for ERROR
    if service.overall_status == service.PASSING_STATUS:
        if service.old_overall_status == service.WARNING_STATUS:
            alert = False  # Don't alert for recovery from WARNING status
    else:
        if service.overall_status == service.CRITICAL_STATUS:
            nicks += [u.profile.irc_nick for u in duty_officers if hasattr(
                u, 'profile') and u.profile.irc_nick]
    c = Context({
        'service': service,
        'users': nicks,
        'host': settings.WWW_HTTP_HOST,
        'scheme': settings.WWW_SCHEME,
        'alert': alert,
    })
    message = Template(chat_template).render(c)
    _send_irc_alert(message)


class IrcMessage(irc.client.SimpleIRCClient):
    """Connects to IRC Server and sends a single message"""
    timeout = 30

    def __init__(self, *args, **kwargs):
        self.done = False
        self.target = kwargs.pop('channel')
        self.message = kwargs.pop('message')
        connection_kwargs = kwargs.pop('connection')
        super(IrcMessage, self).__init__(*args, **kwargs)
        self.connect(**connection_kwargs)

    def on_welcome(self, connection, event):
        """After server connection is made, join channel"""
        if irc.client.is_channel(self.target):
            connection.join(self.target)
        else:
            self.send_msg()

    def on_join(self, connection, event):
        """After channel is joined, send message"""
        self.send_msg()

    def send(self, tick=0.2):
        """Loop to process server output and trigger events"""
        elapsed = 0
        while (not self.done) and elapsed < self.timeout:
            self.ircobj.process_once(tick)
            elapsed += tick
        if not self.done:
            logger.error("Failed to send IRC message to %s", self.target)
        self.connection.close()

    def send_msg(self):
        """Sends message to channel"""
        logger.debug("Sending IRC message to %s: %s", self.target,
                     self.message)
        self.connection.privmsg(self.target, self.message)
        self.done = True


def _send_irc_alert(message):
    channel = settings.IRC_URL.path.strip('/')
    connect_kwargs = {
        'server': settings.IRC_URL.hostname,
        'port': settings.IRC_URL.port,
        'nickname': settings.IRC_URL.username,
        'password': settings.IRC_URL.password,
    }
    # ircs:// is used to denote an SSL connection
    if settings.IRC_URL.scheme == 'ircs':
        ssl_factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        connect_kwargs['connect_factory'] = ssl_factory
    msg = IrcMessage(connection=connect_kwargs, channel=channel,
                     message=message)
    msg.send()


def send_sms_alert(service, users, duty_officers):
    client = TwilioRestClient(
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    mobiles = [u.profile.prefixed_mobile_number for u in users if hasattr(
        u, 'profile') and u.profile.mobile_number]
    if service.is_critical:
        mobiles += [u.profile.prefixed_mobile_number for u in duty_officers if hasattr(
            u, 'profile') and u.profile.mobile_number]
    c = Context({
        'service': service,
        'host': settings.WWW_HTTP_HOST,
        'scheme': settings.WWW_SCHEME,
    })
    message = Template(sms_template).render(c)
    mobiles = list(set(mobiles))
    for mobile in mobiles:
        try:
            client.sms.messages.create(
                to=mobile,
                from_=settings.TWILIO_OUTGOING_NUMBER,
                body=message,
            )
        except Exception, e:
            logger.exception('Error sending twilio sms: %s' % e)


def send_telephone_alert(service, users, duty_officers):
    # No need to call to say things are resolved
    if service.overall_status != service.CRITICAL_STATUS:
        return
    client = TwilioRestClient(
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    mobiles = [u.profile.prefixed_mobile_number for u in duty_officers if hasattr(
        u, 'profile') and u.profile.mobile_number]
    url = 'http://%s%s' % (settings.WWW_HTTP_HOST,
                           reverse('twiml-callback', kwargs={'service_id': service.id}))
    for mobile in mobiles:
        try:
            client.calls.create(
                to=mobile,
                from_=settings.TWILIO_OUTGOING_NUMBER,
                url=url,
                method='GET',
            )
        except Exception, e:
            logger.exception('Error making twilio phone call: %s' % e)


def telephone_alert_twiml_callback(service):
    c = Context({'service': service})
    t = Template(telephone_template).render(c)
    r = twiml.Response()
    r.say(t, voice='woman')
    r.hangup()
    return r
