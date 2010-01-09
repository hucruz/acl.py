import web

import config
from debate import *
from authenticationpy import user_cache_hook, authforms
from authenticationpy.auth import *
from auth_forms import *


urls = ()
urls += (
    '/login', 'login',
    '/logoff', 'logoff',
    '/register(/done|)', 'register',
    '/unregister(/done|)', 'unregister',
    '/reset_password(/done|)', 'reset_password',
    '/confirm/(a|d|r)/([a-f0-9]{64})', 'confirm',
    '/confirm/request_code/(a|d|r|done)', 'request_code',
)
urls += debate_urls

render = web.template.render('templates')


class login:
    def GET(self):
        if web.ctx.session.user:
            path = web.ctx.env.get('HTTP_REFERER', None)
            content = render.already_logged_in(path, web.ctx.session.user)
            return render.base_clean(content)
        self.f = authforms.login_form()
        content = render.login_page(self.f)
        return render.base_clean(content)

    def POST(self):
        self.f = authforms.login_form()
        if not self.f.validates():
            content = render.login_page(self.f)
            return render.base_clean(content)
        self.user = User.get_user(username=self.f.d.username)
        # Add User instance to session storage
        web.ctx.session.user = self.user
        path = web.ctx.env.get('HTTP_REFERER', '/')
        if path == 'http://0.0.0.0:8080/login':
            path = '/'
        raise web.seeother(path)


class register:
    def __init__(self):
        self.f = authforms.register_form()

    def GET(self, done):
        if done:
            content = render.register_success()
            return render.base_clean(content)
        content = render.register_page(self.f)
        return render.base_clean(content)

    def POST(self, done):
        if done: return
        if not self.f.validates():
            return self.render_reg_page()
        # Typical user acount setup procedure with setting custom password, and
        # an activation e-mail.
        self.user = User(username=self.f.d.username,
                         email=self.f.d.email)
        self.user.password = self.f.d.password
        self.user.create(message=render.activation_email().__unicode__())

        raise web.seeother('/register/done')

    def render_reg_page(self):
        content = render.register_page(self.f)
        return render.base_clean(content)


class confirm:
    def GET(self, action, code):
        self.action = action
        self.code = code
        try:
            self.user = User.get_user_by_act_code(self.code)
        except UserAccountError:
            # Activation code is not valid format
            return self.render_failed()

        if not self.user:
            # No account matches the code
            return self.render_failed()

        if self.action == 'a':
            self.activation()
        elif self.action == 'd':
            self.delete()
        elif self.action == 'r':
            self.reset()

        content = render.confirmation_success(self.action)
        return render.base_clean(content)

    def activation(self):
        deadline = 172800 # 48 hours in seconds

        if not self.user.is_interaction_timely('activation', deadline):
            # User took too long to activate
            return self.render_failed()

        # Seems like activation was successful, let's activate the user
        self.user.activate()
        self.user.store()

    def delete(self):
        User.confirm_delete(username = self.user.username)
        # Let's also log off the user
        web.ctx.session.kill()

    def reset(self):
        self.user.confirm_reset()
        self.user.store()
        # Let's also log off the user
        web.ctx.session.kill()

    def render_failed(self):
        f = authforms.email_request_form()
        content = render.confirmation_failed(f, self.action)
        return render.base_clean(content)


class request_code:
    def __init__(self):
        self.f = authforms.email_request_form()

    def GET(self, action):
        self.action = action
        if self.action == 'done':
            content = render.request_success()
            return render.base_clean(content)
        else:
            return self.render_failed()

    def POST(self, action):
        self.action = action

        if self.action == 'done': return

        if not self.f.validates():
            return self.render_failed()
        # Form returns e-mail address so we fetch the user using that.
        self.user = User.get_user(email=self.f.d.email)
        # TODO: The following chunk of code is rather large. There should be a
        # way to give users more convenience here.
        if self.action == 'a':
            self.send_activation_code()
            self.user.set_activation()
        elif self.action == 'd':
            self.send_delete_code()
            self.user.set_delete()
        elif self.action == 'r':
            self.send_reset_code()
            self.user.set_reset()
        else:
            self.render_failed()
        # Since we set the action code in user object in previous lines, we now
        # need to store the user record.
        self.user.store()
        raise web.seeother('/confirm/request_code/done')

    def send_activation_code(self):
        self.user.send_email(subject = web.config.authmail['activation_subject'],
                             message = render.activation_email().__unicode__(),
                             username = self.user.username,
                             email = self.user.email,
                             url = self.user.set_interaction(self.action))

    def send_delete_code(self):
        self.user.send_email(subject = web.config.authmail['delete_subject'],
                             message = render.delete_email().__unicode__(),
                             username = self.user.username,
                             email = self.user.email,
                             url = self.user.set_interaction(self.action))

    def send_reset_code(self):
        self.user.send_email(subject = web.config.authmail['reset_subject'],
                             message = render.reset_email().__unicode__(),
                             username = self.user.username,
                             email = self.user.email,
                             url = self.user.set_interaction(self.action))

    def render_failed(self):
        content = render.confirmation_failed(self.f, self.action)
        return render.base_clean(content)


class logoff:
    def GET(self):
        web.ctx.session.kill()
        raise web.seeother(web.ctx.env.get('HTTP_REFERER', '/'))


class reset_password:
    def __init__(self):
        if not web.ctx.session.user:
            self.f = authforms.email_request_form()
        else:
            self.f = authforms.pw_reset_form()
            self.user = web.ctx.session.user

    def GET(self, done):
        if done:
            content = render.reset_successful()
            return render.base_clean(content)
        if not web.ctx.session.user:
            return self.render_reset_pw_page()
        return self.render_change_pw_page()

    def POST(self, done):
        if done: return
        i = web.input()
        if hasattr(i, 'password'):
            # The POST request has the password parameter, so we assume it was
            # using the change password page.
            if not web.ctx.session.user:
                return self.render_reset_pw_page()
            if not self.f.validates():
                return self.render_change_pw_page()
            self.user.reset_password(password=self.f.d.new,
                                     message = render.pw_change_email().__unicode__())
        else:
            # The POST parameter did not contain the password param, so we
            # assume it was using the e-mail reset request form.
            if not self.f.validates():
                return self.render_reset_pw_page()
            self.user = User.get_user(email=self.f.d.email)
            self.user.reset_password(message = render.pw_change_email().__unicode__())
        
        raise web.seeother('/reset_password/done')


    def render_change_pw_page(self):
        content = render.password_change_page(self.f)
        return render.base_clean(content)

    def render_reset_pw_page(self):
        content = render.password_reset_page(self.f)
        return render.base_clean(content)


class unregister:
    def __init__(self):
        self.f = authforms.login_form()

    def GET(self, done):
        if done:
            content = render.unregister_success()
            return render.base_clean(content)
        if not web.ctx.session.user:
            return self.render_cannot_unregister()
        return self.render_unregister_page()

    def POST(self, done):
        if done: return
        if not web.ctx.session.user:
            return self.render_cannot_unregister()
        if not self.f.validates():
            return self.render_unregister_page()
        # User was authenticated by form validator, so we can remove the
        # account safely sending a confirmation e-mail.
        User.delete(username=web.ctx.session.user.username,
                    message=render.delete_confirmation().__unicode__())
        raise web.seeother('/unregister/done')

    def render_cannot_unregister(self):
        content = render.cannot_unregister()
        return render.base_clean(content)

    def render_unregister_page(self):
        content = render.unregister_page(self.f)
        return render.base_clean(content)


app = web.application(urls, globals())

session = web.session.Session(app, config.sess_store, config.sess_init)
def session_hook():
    web.ctx.session = session
app.add_processor(web.loadhook(session_hook))
app.add_processor(web.loadhook(user_cache_hook))

if __name__ == '__main__':
    print "Starting up..."
    app.run()
