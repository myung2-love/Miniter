from flask import Flask, jsonify, request, Response, current_app, g
from flask_cors import CORS
from Miniter.config import connect_miniter_db as miniter_db
from json import JSONEncoder
from datetime import datetime, timedelta
from functools import wraps
import bcrypt
import jwt



## Default JSON encoder는 set을 JSON으로 변환할 수 없다.
## 그러므로 커스텀 엔코더를 작성해서 set을 list로 변환하여
## JSON으로 변환 가능하게 한다.
class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return super().default(self, obj)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        access_token = request.headers.get('Authorization')
        if access_token is not None:
            try:
                payload = jwt.decode(access_token, current_app.config['JWT_SECRET_KEY'], 'HS256')
            except jwt.InvalidTokenError:
                payload = None

            if payload is None: return Response(status=401)

            user_id = payload['user_id']
            g.user_id = user_id
            g.user = get_user(user_id) if user_id else None
        else:
            return Response(status=401)

        return f(*args, **kwargs)
    return decorated_function

def get_user(user_id):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                SELECT
                    id,
                    name,
                    email,
                    profile
                FROM users
                WHERE id = %(user_id)s
            '''
            params = {
                'user_id':user_id
            }
            cur.execute(sql, params)
            user = cur.fetchone()
    finally:
        db.close()
    
    return {
        'id': user['id'],
        'name': user['name'],
        'email': user['email'],
        'profile': user['profile']
    } if user else None

def insert_user(user):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                INSERT INTO users (
                    name,
                    email,
                    profile,
                    hashed_password
                ) VALUES (
                    %(name)s,
                    %(email)s,
                    %(profile)s,
                    %(password)s
                )
            '''
            cur.execute(sql, user)
            new_user_id = cur.lastrowid

            db.commit()
    finally:
        db.close()

    return new_user_id

def delete_user(user_id):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                DELETE FROM users
                WHERE id = %(user_id)s
            '''
            cur.execute(sql, {'user_id': user_id})
            db.commit()
    finally:
        db.close()

def insert_tweet(user_tweet):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                INSERT INTO tweets (
                    user_id,
                    tweet
                ) VALUES (
                    %(user_id)s,
                    %(tweet)s
                )
            '''
            cur.execute(sql, user_tweet)
            last_tweet_id = cur.lastrowid
            
            db.commit()
    finally:
        db.close()

    return last_tweet_id if last_tweet_id else None

def insert_follow(user_follow):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                INSERT INTO users_follow_list(
                    user_id,
                    follow_user_id
                ) VALUES(
                    %(id)s,
                    %(follow)s
                )
            '''
            cur.execute(sql, user_follow)

            db.commit()
    finally:
        db.close()

def delete_follow(user_unfollow):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                DELETE FROM users_follow_list
                WHERE user_id = %(id)s
                AND follow_user_id = %(unfollow)s
            '''
            cur.execute(sql, user_unfollow)
            db.commit()
    finally:
        db.close()

def get_timeline(user_id):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                SELECT
                    t.user_id,
                    t.tweet
                FROM tweets t
                LEFT JOIN users_follow_list ufl ON ufl.user_id = %(user_id)s
                WHERE t.user_id = %(user_id)s
                OR t.user_id = ufl.follow_user_id
            '''
            cur.execute(sql, {
                'user_id': user_id
            })
            timeline = cur.fetchall()
    finally:
        db.close()
    
    return timeline

def look_up_email(email):
    db = miniter_db()
    try:
        with db.cursor() as cur:
            sql = '''
                SELECT
                    id,
                    hashed_password
                FROM users
                WHERE email = %(email)s
            '''
            cur.execute(sql, {'email':email})
            row = cur.fetchone()
    finally:
        db.close()

    return row if row else None

def create_app(test_config=None):
    app = Flask(__name__)
    app.json_encoder = CustomJSONEncoder
    CORS(app)

    if test_config is None:
        app.config.from_pyfile("config.py")
    else:
        app.config.update(test_config)

    @app.route("/ping", methods=['GET'])
    def ping():
        return "pong"

    @app.route("/sign-up", methods=['POST'])
    def sign_up():
        new_user = request.json
        email = new_user['email']
        password = new_user['password']

        new_user['password'] = bcrypt.hashpw(
            new_user['password'].encode('UTF-8'),
            bcrypt.gensalt()
        )
        new_user_id = insert_user(new_user)
        new_user_info = get_user(new_user_id)

        return jsonify(new_user_info)
    
    @app.route('/user/<int:user_id>', methods=['DELETE'])
    def unregister(user_id):
        delete_user(user_id)

        return '', 200

    @app.route('/login', methods=['POST'])
    def login():
        credential = request.json
        email = credential['email']
        password = credential['password']
        user = look_up_email(email)

        if user and bcrypt.checkpw(password.encode('UTF-8'), user['hashed_password'].encode('UTF-8')):
            user_id = user['id']
            payload = {
                'user_id': user_id,
                'exp'    : datetime.utcnow() + timedelta(seconds = 60*60*24)
            }
            token = jwt.encode(payload, app.config['JWT_SECRET_KEY'], 'HS256')
             
            return jsonify({
                'access_token': token
                })
        else:
            return '', 401

    
    @app.route('/tweet', methods=['POST'])
    @login_required
    def tweet():
        user_tweet = request.json
        user_tweet['user_id'] = g.user_id
        tweet = user_tweet['tweet']

        if len(tweet) > 300:
            return '300자를 초과했습니다', 400

        insert_tweet(user_tweet)

        return '', 200
    
    @app.route('/follow', methods=['POST'])
    @login_required
    def follow():
        payload = request.json
        payload['id'] = g.user_id
        insert_follow(payload)

        return '', 200
    
    @app.route('/unfollow', methods=['POST'])
    @login_required
    def unfollow():
        payload = request.json
        payload['id'] = g.user_id
        delete_follow(payload)

        return '',200

    @app.route('/timeline', methods=['GET'])
    @login_required
    def timeline():
        user_id = g.user_id

        return jsonify({
            'user_id'  : user_id,
            'timeline' : get_timeline(user_id)
            })


    return app






