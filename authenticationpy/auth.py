import re
import random
import hashlib
import datetime
import string

import web

class ConfigurationError(Exception):
    pass

try:
    db = web.config.authdb
except AttributeError:
    raise ConfigurationError('Cannot find database object in web.config.authdb')

try:
    authmail_conf = web.config.authmail
except AttributeError:
    authmail_conf = {}

# TODO: loggin for emails
# TODO: cc site admin on account-related events

sender = authmail_conf.get('sender')
act_subject = authmail_conf.get('activation_subject', 'Account activation')
rst_subject = authmail_conf.get('reset_subject', 'Password reset')
del_subject = authmail_conf.get('delete_subject', 'Account removed')
ssp_subject = authmail_conf.get('suspend_subject', 'Account suspended')

# minimum password length
try:
    min_pwd_length = web.config.min_pwd_length
except:
    min_pwd_length = 4

TABLE = 'authenticationpy_users'

PASSWORD_CHARS = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ234567890'

# Usernames must start with a letter, and can contain letters, numbers, dots,
# dashes, and underscores
username_re = re.compile(r'[A-Za-z]{1}[A-Za-z0-9.-_]{3,39}')

# regexp for e-mail address taken from Django (http://www.djangoproject.com/)
email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"' # quoted-string
    r')@(?:[A-Z0-9]+(?:-*[A-Z0-9]+)*\.)+[A-Z]{2,6}$', # domain
    re.IGNORECASE)

def _generate_password():
    """ Generates a random 8-character string using characters from PASSWORD_CHARS """
    return ''.join([random.choice(PASSWORD_CHARS) for i in range(8)])

def _password_hexdigest(username, salt, password):
    return hashlib.sha256('%s%s%s' % (username, salt, password)).hexdigest()

def _encrypt_password(username, cleartext):
    """ Encrypts the ``cleartext`` password and returns it """

    # TODO: maybe find a better salt generation code, or use longer salt
    salt = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for i in range(16)])
    hexdigest = _password_hexdigest(username, salt, cleartext) 
    return '%s$%s' % (salt, hexdigest)

def _generate_interaction_code(username):
    """ Generate interaction code for use as a URL suffix

    This method returns a tuple of the code to be stored in the database, and
    the hexdigest to be used as the URL.

    The code consists of the code generation timestamp in
    ``YYYY_mm_dd_HH_MM_ssss`` format, and the hexdigest itself separated by the
    dollar sign ``$``. Hexdigest is the SHA-256 hexdigest, and it is 64
    characters long.

    """

    timestamp = datetime.datetime.now()
    formatted_timestamp = timestamp.strftime('%Y%m%d%H%M%s')
    hexdigest = hashlib.sha256('%s%s' % (username, timestamp)).hexdigest()
    return (timestamp, hexdigest)


class UserError(Exception):
    pass


class UserAccountError(UserError):
    pass


class DuplicateUserError(UserError):
    pass


class DuplicateEmailError(UserError):
    pass


class UserInteractionError(UserError):
    pass


class User(object):
    """ User and user management class

    To create a new unsaved user, you have to initialize a User instance
    passing it two required arguments:

    * ``username``: valid username
    * ``email``: a valid e-mail address

    If either of the parameters are missing, ``TypeError`` is raised, and if
    either or both of the arguments are invalid, ``ValueError`` is raised.

    A valid username must start with a letter and can contain only letters,
    numbers, dots, dashes, or underscores. A valid e-mail address must be a
    canonical e-mail addres.

    """

    def __init__(self, username, email):
        # These properties are set directly during __init__
        object.__setattr__(self, 'password', None)
        object.__setattr__(self, 'registered_at', None)
        object.__setattr__(self, 'active', False)
        object.__setattr__(self, '_act_code', None)
        object.__setattr__(self, '_act_time', None)
        object.__setattr__(self, '_act_type', None)
        object.__setattr__(self, '_cleartext', None)
        object.__setattr__(self, '_account_id', None)
        object.__setattr__(self, '_dirty_fields', [])
        object.__setattr__(self, '_pending_pwd', None)
        
        self.username = username
        self.email = email

        # Reset ``_dirty_fields`` so it's empty after initialization
        object.__setattr__(self, '_dirty_fields', [])

        # Ref the cache object
        object.__setattr__(self, '_cache', globals().get('web.ctx.auth_user_cache'))


    def __setattr__(self, name, value):
        if name == 'username':
            if not self._validate_username(value):
                raise ValueError('Invalid username')

        if name == 'email':
            if not self._validate_email(value):
                raise ValueError('Invalid e-mail')

        if name in ['password', '_pending_pwd']:
            if not value:
                raise ValueError('Passwords cannot be blank')
            if len(value) < min_pwd_length:
                raise ValueError('Passwords cannot be shorter than %s characters.' % min_pwd_length)
            self._cleartext = value
            value = _encrypt_password(self.username, value)    

        # store tuples of property name and column name for dirty fields
        if name in ['username', 'email', 'password', 'active']:
            self._dirty_fields.append((name, name))

        if name in ['_act_code', '_act_time', '_act_type', '_pending_pwd']:
            self._dirty_fields.append((name, name[1:]))

        # no errors so far, so go ahead and assign
        object.__setattr__(self, name, value)

    def set_interaction(self, type):
        """ Sets interaction data

        The only required argument is ``type``, which must be one of the
        following:

        * 'activate' ('a' for short)
        * 'delete' ('d' for short)
        * 'reset' ('r' for short)

        If the ``type`` doesn't match any of the allowed values, ``ValueError``
        is raised.

        This method registers the type of the interaction, as well as the time
        of registration, and action code, and returns the activation code. 
        Those pieces of information are stored in ``_act_type``, ``_act_time``, 
        and ``_act_code`` properties respectively.

        """

        if not type in ['activate', 'delete', 'reset', 'a', 'd', 'r']:
            raise ValueError("Interaction type must be 'activate', 'delete', or 'reset'.")
        self._act_time, self._act_code = _generate_interaction_code(self.username)
        self._act_type = type[:1]
        return self._act_code

    def set_activation(self):
        """ Activation wrapper for ``set_interaction`` """
        return self.set_interaction('a')

    def set_delete(self):
        """ Delete confirmation wrapper for ``set_interaction`` """
        return self.set_interaction('d')

    def set_reset(self):
        """ Reset confirmation wrapper for ``set_interaction`` """
        return self.set_interaction('r')

    def clear_interaction(self):
        """ Clears all interaction-related data """
        self._act_type = None
        self._act_time = None
        self._act_code = None

    def is_interaction_timely(self, type, deadline):
        """ Tests whether user action was performed on time 
        
        Required arguments are:

        * ``type``: type of interaction user was supposed to perform
        * ``deadline``: the original deadline in seconds

        ``type`` value should be one of the types used for ``set_interaction``
        method.

        If type does not match the type of outstanding interaction,
        ``UserInteractionError`` is raised.

        If use met the deadline, ``True`` is returned, and ``False`` is
        returned otherwise. Deadline is counted from the time action was
        registered using ``set_interaction`` or any of its wrappers.
        
        """

        if self._act_type is None:
            raise UserInteractionError("There is no registered action.")

        if not type[:1] == self._act_type:
            raise UserInteractionError("Action '%s' is not registered." % type)

        now_time = datetime.datetime.now()
        deadline_time = self._act_time + datetime.timedelta(seconds=deadline)

        return now_time < deadline_time

    def create(self, message=None, activated=False):
        """ Stores a new user optionally gerating a password 
        
        This method fails with ``UserAccountError`` if the ``User`` instance is
        marked as an existing account.

        If ``message`` argument is passed, it is treated as a e-mail message,
        and is automatically sent to user's e-mail address. The message can
        contain template variables (in ``$varname`` form). The variables can
        be one or more of the following:

        * ``$username``: username of the user to be created
        * ``$email``: user's e-mail address
        * ``$password``: user's clear text password
        * ``$usr``: activation URL

        Activation URL is generated only when a ``message`` argument is passed,
        and stored in database.

        If ``activated`` argument is set to True, the user account will be
        activated upon creation. Otherwise, it is *not* activated, which is the
        default. Note that an unactivated account can be always activated
        later.
        
        """

        if db.where(TABLE, what='username', limit=1, username=self.username):
            raise DuplicateUserError("Username '%s' already exists" % self.username)

        if db.where(TABLE, what='email', limit=1, email=self.email):
            raise DuplicateEmailError("Email '%s' already exists" % self.email)

        if not self._new_account:
            raise UserAccountError('Account for %s (%s) is not new' % (self.username,
                                                                       self.email))
        if not self.password:
            self._cleartext = _generate_password()
            self.password = self._cleartext

        if activated:
            self.activate()
        
        if message:
            self.set_activation()
            self.send_email(message=message,
                            subject=act_subject,
                            username=self.username,
                            email=self.email,
                            password=self._cleartext,
                            url=self._act_code)

        self.store()

    def store(self):
        """ Stores a user account """
        if self._dirty_fields:
            # Destroy the cache in an unlikely event that the username or
            # email matches the cached username or email respectively (this
            # happens in tests).
            if web.ctx.auth_user_cache.get('username') == self.username or \
               web.ctx.auth_user_cache.get('email') == self.email:
                web.ctx.auth_user_cache = {}

            transaction = db.transaction()
            try:
                if self._new_account:
                    if not self.password:
                        raise UserAccountError('Password cannot be blank.')
                    db.insert(TABLE, **self._data_to_insert)
                    record = db.where(TABLE, what='id',
                                      limit=1,
                                      username=self.username)[0]
                    self._account_id = record.id
                else:
                    db.update(TABLE, where='id = $id',
                              vars={'id': self._account_id},
                              **self._data_to_store)
            except:
                transaction.rollback()
                raise
            else:
                transaction.commit()

        # nothing to store
        pass

    def activate(self):
        self.clear_interaction()
        self.active = True

    def authenticate(self, password):
        """ Test ``password`` and return boolean success status """
        if not self.active:
            raise UserAccountError('Cannot authenticate inactive account')
        salt, crypt = self.password.split('$')
        return _password_hexdigest(self.username,
                                   salt,
                                   password) == crypt

    def reset_password(self, password=None, message=None, confirmation=None):
        """ Resets the user password 
        
        ``password`` argument is optional and it is the new user password to be
        saved. If no password is supplied, a random password will be generated.
        
        If you specify the ``message``, an e-mail is sent to the user's e-mail
        address. The ``message`` is a string, and it may contain template
        variables in ``$varname`` form. Following variables are available:

        * ``$username``: username of the user to be created
        * ``$email``: user's e-mail address
        * ``$password``: user's clear text password
        * ``$url``: confirmation url

        Optional argument ``confirmation`` can be used to disable setting the
        password. When ``confirmation`` is set to ``True`` actual password is
        not set. It is hashed and stored in a separate column, and can be set
        later by using the ``confirm_set_pwd`` method. By default
        ``confirmation`` argument is ``False``. However, if you pass the
        ``message`` argument, the default changes to ``True``. You only need to
        set ``confirmation`` to ``True`` if you are not passing the ``message``
        argument.

        """

        if not password:
            password = _generate_password()

        if confirmation is None and message:
            confirmation = True

        if confirmation:
            self._pending_pwd = password
        else:
            self.password = password

        if message:
            self.set_reset()
            self.send_email(message=message,
                            subject=rst_subject,
                            username=self.username,
                            email=self.email,
                            password=self._cleartext,
                            url=self._act_code)

        self.store()

    def confirm_reset(self):
        """ Assign pending password as new """
        self.clear_interaction()
        object.__setattr__(self, 'password', self._pending_pwd)
        object.__setattr__(self, '_pending_pwd', None)
        self._dirty_fields.extend([('password', 'password'), 
                                   ('_pending_pwd', 'pending_pwd')])

    def send_email(self, message, subject, sender=sender, **kwargs):
        """ Send an arbitrary e-mail message to the user 
        
        Required argument for this method are:

        * ``message``: the body of the e-mail
        * ``subject``: e-mail's subject
        
        ``sender`` argument is optional, and it defaults to
        ``web.config.authmail['sender']``, which is usually the e-mail address
        of your site.

        Optionally, you can use ``kwargs`` to set template variables. The
        template variables follow the ``$varname`` pattern used by Python's
        built-in string formatting facilities. Any occurence of ``$varname`` in
        your message string will be replaced by appropriate variables you
        specify in ``kwargs``. For example::

            >>> user.send_email(message='Hi, $username!', subject='Hi',
            ...                 username='some_user')
            # results in a message 'Hi, some_user!'

        If ``kwargs`` are omitted, the default variables are provided. Those
        are:

        * ``$sender``: the sender's e-mail address
        * ``$username``: username of the receiving user
        * ``$email``: e-mail address of the receiving user

        If for some reason, the e-mail cannot be sent (e.g, because
        ``sendmail`` is not available on your system of SMTP parameters are
        incorrect, ``send_email`` will not raise any exceptions. The best way
        to make sure ``send_email`` is working is to send yourself a message.

        For information on how to set up web.py's e-mail sending facilities,
        read the web.py API documentation on `web.utils module
        <http://webpy.org/docs/0.3/api#web.utils>`.
        
        """
        if not kwargs:
            kwargs = {'sender': sender,
                      'username': self.username,
                      'email': self.email }
        template = string.Template(message)
        body = template.substitute(**kwargs)
        try:
            
            web.utils.sendmail(from_address=sender,
                               to_address=self.email,
                               subject=subject,
                               message=body)
        except OSError:
            pass

    @property
    def _data_to_insert(self):
        """ Returns a dictionary of data to insert """
        insert_dict = {'username': self.username,
                       'email': self.email,
                       'password': self.password,
                       'active': self.active}
        if self._act_code:
            insert_dict['act_code'] = self._act_code
            insert_dict['act_time'] = self._act_time
            insert_dict['act_type'] = self._act_type
        return insert_dict

    @property
    def _data_to_store(self):
        """ Returns a dictionary of dirty field names and values """
        store_dict = {}
        for field in self._dirty_fields:
            store_dict[field[1]] = self.__dict__[field[0]]
        return store_dict

    @property
    def _new_account(self):
        if self._account_id:
            return False
        return True

    @property
    def id(self):
        return self._account_id or None
       
    @classmethod
    def _validate_username(cls, username):
        return username_re.match(username)

    @classmethod
    def _validate_email(cls, email):
        return email_re.match(email)

    @classmethod
    def delete(cls, username=None, email=None, message=None, confirmation=None):
        """ Deletes user account optionally sending an e-mail

        You must supply either ``username`` or ``email`` arguments to delete a
        user account. In case either of the required arguments are missing,
        ``UserAccountError`` is raised.

        If you specify a ``message`` argument, the user account is not deleted,
        but an e-mail is sent to the user. The ``message`` template may contain
        the following template variables in ``$varname`` form:

        * ``$username``: account's username
        * ``$email``: user's e-mail address
        * ``$url``: account removal confirmation URL suffix

        You can use the optional ``confirmation`` argument to disable user
        account deletion even if the ``message`` argument is missing, in cases
        where you have a confirmation mechanism of your own. You can also use
        the ``confirmation`` argument to force account removal even if you
        specify the ``message``.

        The default value of ``confirmation`` argument is ``False``, but it
        defaults to ``True`` if ``message`` argument is used.

        """

        if username is None and email is None:
            raise UserAccountError('No user information for deletion.')
       
        delete_dict = {}

        if username:
            if web.ctx.auth_user_cache.get('username') == username:
                # Reset the chace before we delete the user
                web.ctx.auth_user_cache = {}
            delete_dict['username'] = username

        if email:
            if web.ctx.auth_user_cache.get('email') == email:
                # Reset the chace before we delete the user
                web.ctx.auth_user_cache = {}
            delete_dict['email'] = email

        if confirmation is None and message:
            confirmation = True

        if message:
            if username:
                user = cls.get_user(username=username)
            else:
                user = cls.get_user(email=email)

            user.set_delete()
            user.send_email(message=message,
                            subject=del_subject,
                            username=user.username,
                            email=user.email,
                            url=user._act_code)
            user.store()
        
        if not confirmation:
            db.delete(TABLE, where=web.db.sqlwhere(delete_dict))

    @classmethod
    def confirm_delete(cls, username=None, email=None):
        """ Wrapper around ``delete`` to instantly remove an account """
        cls.delete(username=username, email=email)

    @classmethod
    def suspend(cls, username=None, email=None, message=None):
        """ Suspend a user account

        Required arguments are ``username`` and ``email``. If either is
        missing, ``UserAccountError`` will be raised.

        If you specify a ``message``, an e-mail message will be sent to the
        affected account. You can include template variables in your
        ``message`` text in ``$varname`` format. The available variables are:

        * ``$username``: account's username
        * ``$email``: user's e-mail address

        Note that an account will be suspended regardless of whether you pass
        the ``message`` argument or not.

        """

        if not username and not email:
            raise UserAccountError('No information for account suspension')
        
        suspend_dict = {}
        if username:
            suspend_dict['username'] = username
        if email:
            suspend_dict['email'] = email

        if message:
            if username:
                user = cls.get_user(username=username)
            else:
                user = cls.get_user(email=email)

            user.send_email(message=message,
                            subject=ssp_subject,
                            username=user.username,
                            email=user.email)

        # Destroy the cache
        web.ctx.auth_user_cache = {}

        db.update(TABLE, where=web.db.sqlwhere(suspend_dict), active=False)

    @classmethod
    def get_user(cls, username=None, email=None):
        """ Get user from the database and return ``User`` instance

        Finds a user account that matches either or both of the optional
        arguments:

        * ``username``: username of the account
        * ``email``: user's e-mail address

        If neither of the arguments are supplied, ``UserAccountError`` is
        raised. If no match is found, ``None`` is returned.

        Returned accounts always have ``_new_account`` property set to False,
        but this is meant for internal use only. Nevertheless, if you need to
        know if the account is a new (unsaved) one, you can access this
        property.

        A successful query returns a ``User`` instance.

        """

        if username is None and email is None:
            raise UserAccountError('No user account information to look for')

        select_dict = {}
        if username:
            if not cls._validate_username(username):
                raise ValueError("'%s' does not look like a valid username" % username)
            if web.ctx.auth_user_cache.get('username') == username:
                return web.ctx.auth_user_cache['object']
            select_dict['username'] = username
        if email:
            if not cls._validate_email(email):
                raise ValueError("'%s' does not look like a valid e-mail" % email)
            if web.ctx.auth_user_cache.get('email') == email:
                return web.ctx.auth_user_cache['object']
            select_dict['email'] = email

        records = db.where(TABLE, **select_dict)

        if not records:
            # There is nothing to return
            web.ctx.auth_user_cache = {}
            return None

        return cls._cache_and_return(records[0])
        
    @classmethod
    def get_user_by_act_code(cls, act_code):
        """ Gets a user account by interaction code """
        if not re.match(r'^[a-f0-9]{64}$', act_code):
            raise UserAccountError('Action code is not the right format.')

        if web.ctx.auth_user_cache.get('act_code') == act_code:
            return web.ctx.auth_user_cache['object']

        records = db.where(TABLE, act_code=act_code)
        
        if not records:
            # There is nothing to return
            web.ctx.auth_user_cache = {}
            return None

        return cls._cache_and_return(records[0])

    @classmethod
    def _cache_and_return(cls, record):
        web.ctx.auth_user_cache['username'] = record.username
        web.ctx.auth_user_cache['email'] = record.email
        web.ctx.auth_user_cache['act_code'] = record.act_code
        web.ctx.auth_user_cache['object'] = cls._map_user_properties(record)
        return web.ctx.auth_user_cache['object']

    @classmethod
    def _map_user_properties(cls, user_account):
        """ Maps user records to instance properties """

        try:
            user_username = user_account.username
            user_email = user_account.email
            user_dict = {
                '_account_id': user_account.id,
                'password': user_account.password,
                '_pending_pwd': user_account.pending_pwd,
                '_act_code': user_account.act_code,
                '_act_time': user_account.act_time,
                '_act_type': user_account.act_type,
                'registered_at': user_account.registered_at,
                'active': user_account.active,
            }
        except AttributeError:
            raise UserAccountError('Missing data for user with id %s)' % user_account.id)
        
        user = User(username=user_username,
                    email=user_email)

        for key in user_dict.keys():
            object.__setattr__(user, key, user_dict[key])

        return user

    @classmethod
    def exists(cls, username=None, email=None):
        if not username and not email:
            raise TypeError('You must supply username or email argument.')
        where_kws = {}
        if username:
            where_kws['username'] = username
        if email:
            where_kws['email'] = email

        where_clause = web.db.sqlwhere(where_kws, grouping=' OR ')
        if len(db.select(TABLE, what='id', where=where_clause)) > 0:
            return True
        return False

