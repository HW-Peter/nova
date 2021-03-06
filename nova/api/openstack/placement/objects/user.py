#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import sqlalchemy as sa

from nova.api.openstack.placement import db_api
from nova.api.openstack.placement import exception
from nova.db.sqlalchemy import api_models as models

CONF = cfg.CONF
USER_TBL = models.User.__table__


@db_api.placement_context_manager.writer
def ensure_incomplete_user(ctx):
    """Ensures that a user record is created for the "incomplete consumer
    user". Returns the internal ID of that record.
    """
    incomplete_id = CONF.placement.incomplete_consumer_user_id
    sel = sa.select([USER_TBL.c.id]).where(
        USER_TBL.c.external_id == incomplete_id)
    res = ctx.session.execute(sel).fetchone()
    if res:
        return res[0]
    ins = USER_TBL.insert().values(external_id=incomplete_id)
    res = ctx.session.execute(ins)
    return res.inserted_primary_key[0]


@db_api.placement_context_manager.reader
def _get_user_by_external_id(ctx, external_id):
    users = sa.alias(USER_TBL, name="u")
    cols = [
        users.c.id,
        users.c.external_id,
        users.c.updated_at,
        users.c.created_at
    ]
    sel = sa.select(cols)
    sel = sel.where(users.c.external_id == external_id)
    res = ctx.session.execute(sel).fetchone()
    if not res:
        raise exception.UserNotFound(external_id=external_id)

    return dict(res)


@base.VersionedObjectRegistry.register_if(False)
class User(base.VersionedObject):

    fields = {
        'id': fields.IntegerField(read_only=True),
        'external_id': fields.StringField(nullable=False),
    }

    @staticmethod
    def _from_db_object(ctx, target, source):
        for field in target.fields:
            setattr(target, field, source[field])

        target._context = ctx
        target.obj_reset_changes()
        return target

    @classmethod
    def get_by_external_id(cls, ctx, external_id):
        res = _get_user_by_external_id(ctx, external_id)
        return cls._from_db_object(ctx, cls(ctx), res)

    def create(self):
        @db_api.placement_context_manager.writer
        def _create_in_db(ctx):
            db_obj = models.User(external_id=self.external_id)
            try:
                db_obj.save(ctx.session)
            except db_exc.DBDuplicateEntry:
                raise exception.UserExists(external_id=self.external_id)
            self._from_db_object(ctx, self, db_obj)
        _create_in_db(self._context)
