import datetime
import time

import web
from nose.tools import *

database = web.database(dbn='postgres', db='authenticationpy_test', user='postgres')
web.config.authdb = database
web.config.authmail = {'sender': 'admin@mysite.com',
                       'activation_subject': 'MySite.com Activation E-Mail',}

from authenticationpy import user_cache_hook, auth
from authenticationpy import authforms

invalid_usernames = (
    '12hours', # starts with a number
    '$mister', # starts with a special character
    '_boogy', # another one starting with a spec char
    '-peenutz', # yet another
)

invalid_emails = (
    # FIXME: Find more representative samples of FU'd emails
    '@nouser.com',
    '@double@atmark@server.com',
)

user_cache_hook()

def setup_table():
    # create table for User object
    database.query("""
                   DROP TABLE IF EXISTS authenticationpy_users CASCADE;
                   CREATE TABLE authenticationpy_users (
                     id               SERIAL PRIMARY KEY,
                     username         VARCHAR(40) NOT NULL UNIQUE,
                     email            VARCHAR(80) NOT NULL UNIQUE,
                     password         CHAR(81) NOT NULL,
                     pending_pwd      CHAR(81),
                     act_code         CHAR(64),
                     act_time         TIMESTAMP,
                     act_type         CHAR(1),
                     registered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     active           BOOLEAN DEFAULT 'false' 
                   );
                   CREATE UNIQUE INDEX username_index ON authenticationpy_users
                   USING btree (username);
                   CREATE UNIQUE INDEX email_index ON authenticationpy_users
                   USING btree (username);
                   """)

def teardown_table():
    database.query("""
                   DROP TABLE IF EXISTS authenticationpy_users CASCADE;
                   """)

def test_username_regexp():
    for username in invalid_usernames:
        yield username_check, username

def username_check(string):
    assert_false(auth.username_re.match(string))

def test_email_regexp():
    for e in invalid_emails:
        yield email_check, e

def email_check(string):
    assert_false(auth.username_re.match(string))

@raises(TypeError)
def test_create_user_missing_args():
    auth.User()

def test_create_user_bad_username():
    for u in invalid_usernames:
        yield create_bad_username_check, u

@raises(ValueError)
def create_bad_username_check(string):
    auth.User(username=string, email="valid@email.com")

@with_setup(setup=setup_table, teardown=teardown_table)
def test_create_user_bad_email():
    for e in invalid_emails:
        yield create_bad_email_check, e

@raises(ValueError)
def create_bad_email_check(string):
    auth.User(username='myuser', email=string)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_new_user_instance_has_no_password():
    user = auth.User(username='myuser', email='valid@email.com')
    assert user.password is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_setting_password():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    assert len(user.password) == 81

@with_setup(setup=setup_table, teardown=teardown_table)
def test_save_new_instance_no_password():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    assert len(user.password) == 81

@with_setup(setup=setup_table, teardown=teardown_table)
def test_save_new_instance_has_cleartext():
    user = auth.User(username='myuser', email='valid@email.com')
    assert user._cleartext is None
    user.create()
    assert len(user._cleartext) == 8

@with_setup(setup=setup_table, teardown=teardown_table)
def test_create_database_record():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    assert len(database.select('authenticationpy_users')) == 1
    record = database.select('authenticationpy_users')[0]
    assert record.username == 'myuser'

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.DuplicateUserError)
def test_double_create_record():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user.create()

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.DuplicateUserError)
def test_create_duplicate_username():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User(username='myuser', email='other@email.com')
    user.create()

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.DuplicateEmailError)
def test_create_duplicate_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User(username='otheruser', email='valid@email.com')
    user.create()

@with_setup(setup=setup_table, teardown=teardown_table)
def test_activation_withut_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    assert_false(user.active)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_create_with_email_sets_act_code():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create(message='This is an activation mail')
    assert len(user._act_code) == 64

@with_setup(setup=setup_table, teardown=teardown_table)
def test_activation_code_in_db():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create(message='This is the activation mail')
    record = database.select('authenticationpy_users',
                             what='act_code',
                             where="username = 'myuser'",
                             limit=1)[0]
    assert record.act_code == user._act_code

@with_setup(setup=setup_table, teardown=teardown_table)
def test_activation_on_create():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create(activated=True)
    record = database.select('authenticationpy_users',
                             what='active',
                             where="username = 'myuser'",
                             limit=1)[0]
    assert record.active == True

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_by_username():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    assert user.email == 'valid@email.com'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_by_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(email='valid@email.com')
    assert user.username == 'myuser'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_by_username_and_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser', email='valid@email.com')
    assert user.username == 'myuser'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_nonexistent_username():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='nouser')
    assert user is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_nonexistent_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(email='not.me@email.com')
    assert user is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_with_combined_nonexistent():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='nouser', email='valid@email.com')
    assert user is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_with_combined_nonexistent_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser', email='not.me@email.com')
    assert user is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_sets_cache():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    assert web.ctx.auth_user_cache
    assert web.ctx.auth_user_cache.get('username')
    assert web.ctx.auth_user_cache.get('email')
    assert web.ctx.auth_user_cache.get('object')
    assert web.ctx.auth_user_cache.get('object') is user
    user = auth.User.get_user(username='myuser')
    assert web.ctx.auth_user_cache.get('object') is user

@with_setup(setup=setup_table, teardown=teardown_table)
def test_existing_user_has_no_new_account_flag():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    assert user._new_account == False

@with_setup(setup=setup_table, teardown=teardown_table)
def test_authenticate():
    password = 'abc123'
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = password
    user.create(activated=True)
    assert user.authenticate(password)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_authenticate_wrong_password():
    password = 'abc123'
    user = auth.User(username='myuser', email='valid@email.com')
    user.create(activated=True)
    assert_false(user.authenticate(password))

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserAccountError)
def test_authenticate_inactive_account():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create()
    user.authenticate('abc123')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_user_has_dirty_fields_property():
    user = auth.User(username='myuser', email='valid@email.com')
    assert user._dirty_fields == []

@with_setup(setup=setup_table, teardown=teardown_table)
def test_dirty_fields_empty_after_get_user():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    assert user._dirty_fields == []

@with_setup(setup=setup_table, teardown=teardown_table)
def test_dirty_fields_list_on_modification():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    user.email = 'another@email.com'
    assert user._dirty_fields == [('email', 'email')]

@with_setup(setup=setup_table, teardown=teardown_table)
def test_dirty_fields_with_private_properties():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    user._act_code = auth._generate_interaction_code(user.username)
    assert user._dirty_fields == [('_act_code', 'act_code')]

@with_setup(setup=setup_table, teardown=teardown_table)
def test_data_to_store():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    user.username = 'otheruser'
    user.email = 'another@email.com'
    assert user._data_to_store == {'username': 'otheruser', 
                                   'email': 'another@email.com'}

@with_setup(setup=setup_table, teardown=teardown_table)
def test_store_modifications():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    user = auth.User.get_user(username='myuser')
    user.username = 'otheruser'
    user.store()
    user = auth.User.get_user(email='valid@email.com')
    assert user.username == 'otheruser'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_change_password():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.authenticate('abc123')
    user.password = '123abc'
    user.store()
    user = auth.User.get_user(username='myuser')
    assert user.authenticate('123abc')

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(ValueError)
def test_change_password_with_short_password():
    auth.min_pwd_length = 2
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'a'

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(ValueError)
def test_change_password_with_blank_password():
    auth.min_pwd_length = 0
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = ''

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc')
    user = auth.User.get_user(username='myuser')
    assert user.authenticate('123abc')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password_with_random_pwd():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password()
    password = user._cleartext
    user = auth.User.get_user(username='myuser')
    assert user.authenticate(password)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password_with_confirmation_reset_code():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc', 
                        message='Please visit http://mysite.com/confirm/$url')
    assert len(user._act_code) == 64

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password_with_confirmation():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc', 
                        message='Please visit http://mysite.com/confirm/$url')
    assert len(user._pending_pwd) == 81

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password_old_pwd_still_valid():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc', 
                        message='Please visit http://mysite.com/confirm/$url')
    assert user.authenticate('abc123')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_reset_password_with_notification():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc',
                        message='Your password has been reset',
                        confirmation=False)
    assert user.authenticate('123abc')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_confirm_reset():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc', 
                        message='Please visit http://mysite.com/confirm/$url')
    user = auth.User.get_user(username='myuser')
    user.confirm_reset()
    assert user.authenticate('123abc')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_confirm_reset_with_storing():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    user = auth.User.get_user(username='myuser')
    user.reset_password('123abc', 
                        message='Please visit http://mysite.com/confirm/$url')
    user = auth.User.get_user(username='myuser')
    user.confirm_reset()
    user.store()
    user = auth.User.get_user(username='myuser')
    assert user.authenticate('123abc')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_user_record():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(username='myuser')
    assert not auth.User.get_user(username='myuser')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_user_by_email():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(email='valid@email.com')
    assert not auth.User.get_user(username='myuser')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_user_with_confirmation():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(username='myuser',
                     message='Click http://mysite.com/delete/$url to confirm')
    user = auth.User.get_user(username='myuser')
    assert len(user._act_code) == 64

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_user_with_confirmation_no_message():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(username='myuser', confirmation=True)
    assert auth.User.get_user(username='myuser')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_user_with_notification():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(username='myuser',
                     message='Click http://mysite.com/delete/$url to confirm',
                     confirmation=False)
    assert not auth.User.get_user(username='myuser')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_delete_confirmation():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    auth.User.delete(username='myuser', confirmation=True)
    auth.User.confirm_delete(username='myuser')
    assert not auth.User.get_user(username='myuser')

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserAccountError)
def test_suspend_account():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    auth.User.suspend(username='myuser')
    user = auth.User.get_user(username='myuser')
    user.authenticate('abc123')

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserAccountError)
def test_suspend_with_message():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create(activated=True)
    auth.User.suspend(username='myuser', message='Your account was suspended')
    user = auth.User.get_user(username='myuser')
    user.authenticate('abc123')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_set_interaction_sets_act_code():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_interaction('activate')
    assert len(user._act_code) == 64

@with_setup(setup=setup_table, teardown=teardown_table)
def test_set_interaction_sets_act_time():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_interaction('activate')
    assert type(user._act_time) == datetime.datetime

@with_setup(setup=setup_table, teardown=teardown_table)
def test_set_interaction_sets_act_type():
    for type in [('activate', 'a'), ('delete', 'd'), ('reset', 'r')]:
        yield check_act_type, type

def check_act_type(type):
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_interaction(type[0])
    assert user._act_type == type[1]

@with_setup(setup=setup_table, teardown=teardown_table)
def test_set_interaction_returns_code():
    user = auth.User(username='myuser', email='valid@email.com')
    code = user.set_interaction('a')
    assert code == user._act_code

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(ValueError)
def test_wrong_interaction_type():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_interaction('bogus')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_activation_interaction():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    assert user._act_type == 'a'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_activation_returns_code():
    user = auth.User(username='myuser', email='valid@email.com')
    code = user.set_activation()
    assert code == user._act_code

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_delete_interaction():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_delete()
    assert user._act_type == 'd'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_delete_returns_code():
    user = auth.User(username='myuser', email='valid@email.com')
    code = user.set_delete()
    assert code == user._act_code

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_reset_interaction():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_reset()
    assert user._act_type == 'r'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_wrapper_reset_returns_code():
    user = auth.User(username='myuser', email='valid@email.com')
    code = user.set_reset()
    assert code == user._act_code

@with_setup(setup=setup_table, teardown=teardown_table)
def test_interaction_timeout():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    assert user.is_interaction_timely(type='a', deadline=10)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_interaction_past_deadline():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    time.sleep(2)
    assert not user.is_interaction_timely('a', 1)

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserInteractionError)
def test_interaction_with_wrong_type():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    user.is_interaction_timely('r', 10)

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserInteractionError)
def test_interaction_timely_when_no_interaction():
    user = auth.User(username='myuser', email='valid@email.com')
    user.is_interaction_timely('a', 10)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_interaction_data_stored_properly():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    user.create()
    user = auth.User.get_user(username='myuser')
    assert user._act_type == 'a'

@with_setup(setup=setup_table, teardown=teardown_table)
def test_clear_interaction_clears_act_type():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    user.create()
    user = auth.User.get_user(username='myuser')
    user.clear_interaction()
    assert user._act_type is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_get_user_by_action_code():
    user = auth.User(username='myuser', email='valid@email.com')
    user.set_activation()
    user.create()
    same_user = auth.User.get_user_by_act_code(user._act_code)
    assert same_user.username == 'myuser'

@with_setup(setup=setup_table, teardown=teardown_table)
@raises(auth.UserAccountError)
def test_get_user_by_action_code_with_wrong_code():
    auth.User.get_user_by_act_code('bogus code')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_id_property():
    user = auth.User(username='myuser', email='valid@email.com')
    assert user.id is None

@with_setup(setup=setup_table, teardown=teardown_table)
def test_id_property_on_saved_account():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    assert user.id == 1

@with_setup(setup=setup_table, teardown=teardown_table)
def test_user_exist():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    assert auth.User.exists(username='myuser')
    assert auth.User.exists(email='valid@email.com')
    assert auth.User.exists(username='myuser', email='valid@email.com')
    assert auth.User.exists(username='myuser', email='some@other.com')
    assert auth.User.exists(username='none', email='valid@email.com')
    assert not auth.User.exists(username='none')
    assert not auth.User.exists(email='some@other.com')

@raises(TypeError)
def test_user_exists_with_no_args():
    auth.User.exists()

def test_login_form():
    login_form = authforms.login_form()
    assert isinstance(login_form, web.form.Form)

def test_login_form_validates_username():
    login_form = authforms.login_form()
    # Feed it a really short username:
    assert not login_form.username.validate('us')

def test_login_password_nonempty():
    login_form = authforms.login_form()
    # Feed it an emtpy string
    assert not login_form.password.validate('')

def test_login_min_pwd_length():
    login_form = authforms.login_form()
    assert not login_form.password.validate('pas')
    assert login_form.password.validate('pass')

@with_setup(setup=setup_table, teardown=teardown_table)
def test_login_with_real_account():
    user = auth.User(username='myuser', email='valid@email.com')
    user.password = 'abc123'
    user.create()
    login_form = authforms.login_form()
    assert not login_form.validates(web.storify({
        'username': 'myuser',
        'password': 'abc123',
    }))
    user.activate()
    user.store()
    assert login_form.validates(web.storify({
        'username': 'myuser',
        'password': 'abc123',
    })), login_form.note
    assert not login_form.validates(web.storify({
        'username': 'myuser',
        'password': 'wrong password',
    }))
    assert not login_form.validates(web.storify({
        'username': 'wrong',
        'password': 'abc123',
    }))

def test_registration_form():
    reg_form = authforms.register_form()
    assert isinstance(reg_form, web.form.Form)

def test_registration_email_validation():
    reg_form = authforms.register_form()
    reg_from = authforms.register_form()
    assert reg_form.email.validate('valid@email.com')
    for e in invalid_emails:
        yield check_reg_invalid_emails, e

def check_reg_invalid_emails(email):
    reg_form = authforms.register_form()
    assert not reg_form.email.validate(email)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_registration_pw_confirmation():
    reg_form = authforms.register_form()
    assert reg_form.validates(web.storify({
        'username': 'myuser',
        'email': 'valid@email.com',
        'password': 'abc123',
        'confirm': 'abc123'
    })), reg_form.note
    assert not reg_form.validates(web.storify({
        'username': 'myuser',
        'email': 'valid@email.com',
        'password': 'abc123',
        'confirm': 'wont repeat'
    }))

@with_setup(setup=setup_table, teardown=teardown_table)
def test_registration_fails_if_user_exists():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    reg_form = authforms.register_form()
    assert not reg_form.validates(web.storify({
        'username': 'myuser',
        'email': 'valid@email.com',
        'password': 'abc123',
        'confirm': 'abc123',
    }))
    assert not reg_form.validates(web.storify({
        'username': 'otheruser',
        'email': 'valid@email.com', # still the same e-mail
        'password': 'abc123',
        'confirm': 'abc123',
    }))
    assert not reg_form.validates(web.storify({
        'username': 'myuser',
        'email': 'other@email.com',
        'password': 'abc123',
        'confirm': 'abc123',
    }))

def test_reset_form():
    reset_form = authforms.pw_reset_form()
    assert isinstance(reset_form, web.form.Form)

def test_set_new_password():
    reset_form = authforms.pw_reset_form()
    assert reset_form.validates(web.storify({
        'password': 'abc123',
        'new': '123abc',
        'confirm': '123abc'
    }))

def test_wrong_new_password():
    reset_form = authforms.pw_reset_form()
    assert not reset_form.validates(web.storify({
        'password': 'abc123',
        'new': '123abc',
        'confirm': '123123'
    }))

def test_email_request_form():
    email_form = authforms.email_request_form()
    assert isinstance(email_form, web.form.Form)

@with_setup(setup=setup_table, teardown=teardown_table)
def test_email_belongs_to_account_validation():
    user = auth.User(username='myuser', email='valid@email.com')
    user.create()
    email_form = authforms.email_request_form()
    assert email_form.validates(web.storify({
        'email': user.email,
    })), email_form.note
    assert not email_form.validates(web.storify({
        'email': 'some@other.com',
    }))
