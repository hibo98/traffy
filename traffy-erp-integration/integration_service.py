"""
 Copyright (C) 2021 Falk Seidl <hi@falsei.de>

 Author: Falk Seidl <hi@falsei.de>

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License as
 published by the Free Software Foundation; either version 2 of the
 License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful, but
 WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program; if not, see <http://www.gnu.org/licenses/>.
"""
import database_manager
import pyaes
import codecs
import config
from models import ERPMaster, IdentityUpdate, TraffyDormitory, TraffyIdentity, IdentityNew, IdentityDelete


def decrypt_data(data):
    if data is None:
        return None

    unhex = codecs.decode(data, "hex")
    decrypter = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(config.DECRYPTION_KEY_STRING.encode(),
                                                            config.DECRYPTION_INIT_VECTOR))
    decrypted_data = decrypter.feed(unhex)
    try:
        decrypted_data += decrypter.feed()
    except ValueError:
        decrypted_data = data.encode()

    return codecs.decode(decrypted_data, config.REMOTE_CHARSET)


class IntegrationService:
    erp_session = NotImplemented
    traffy_session = NotImplemented

    def run_service(self):
        self.erp_session = database_manager.DatabaseManagerERP().create_session()
        erp_master_data_query = self.erp_session.query(ERPMaster).filter(ERPMaster.dormitory_id.in_(config.RELEVANT_DORMITORY_IDS)).all()

        self.traffy_session = database_manager.DatabaseManagerTraffy().create_session()

        self.__clear_identity_updates_table()

        for erp_row in erp_master_data_query:
            erp_debitor_id = erp_row.debitor_id
            erp_first_name = decrypt_data(erp_row.first_name)
            erp_last_name = decrypt_data(erp_row.last_name)
            erp_mail = decrypt_data(erp_row.mail)
            erp_traffy_dormitory_id = (self.traffy_session.query(TraffyDormitory)
                                       .filter_by(internal_id=erp_row.dormitory_id).first().id)
            erp_room = erp_row.room
            erp_ib_needed = erp_row.ib_needed
            erp_ib_expiry_date = erp_row.ib_expiry_date
            erp_contract_expiry_date = erp_row.contract_expiry_date

            if erp_ib_needed == "J":
                erp_ib_needed = True
            else:
                erp_ib_needed = False

            traffy_identity_query = (self.traffy_session.query(TraffyIdentity)
                                     .filter_by(customer_id=erp_debitor_id).all())

            if len(traffy_identity_query) > 0:
                for traffy_identity in traffy_identity_query:
                    update_first_name = None
                    update_last_name = None
                    update_mail = None
                    update_dormitory_id = None
                    update_room = None

                    if traffy_identity.first_name != erp_first_name:
                        update_first_name = erp_first_name.strip().strip(';').strip()
                    if traffy_identity.last_name != erp_last_name:
                        update_last_name = erp_last_name.strip().strip(';').strip()
                    if traffy_identity.mail != erp_mail:
                        update_mail = erp_mail.strip().strip(';').strip()
                    if traffy_identity.dormitory_id != erp_traffy_dormitory_id:
                        update_dormitory_id = erp_traffy_dormitory_id
                    if traffy_identity.room != erp_room:
                        update_room = erp_room

                    if update_first_name is not None \
                        or update_last_name is not None \
                        or update_mail is not None \
                        or update_dormitory_id is not None \
                        or update_room is not None:
                        self.__mark_identity_as_updatable(traffy_identity.id,
                                                          update_first_name,
                                                          update_last_name,
                                                          update_mail,
                                                          update_dormitory_id,
                                                          update_room)
            else:
                self.__mark_identity_as_new(customer_id=erp_debitor_id,
                                            first_name=erp_first_name,
                                            last_name=erp_last_name,
                                            mail=erp_mail,
                                            dormitory_id=erp_traffy_dormitory_id,
                                            room=erp_room)
        self.traffy_session.commit()

        traffy_master_data_query = self.traffy_session.query(TraffyIdentity).all()
        for traffy_row in traffy_master_data_query:
            if traffy_row.customer_id == 0:
                continue
            erp_identity_query = self.erp_session.query(ERPMaster).filter_by(debitor_id=traffy_row.customer_id).all()
            if len(erp_identity_query) == 0:
                self.__mark_identity_as_deletable(traffy_row.id)

        self.traffy_session.commit()
        self.traffy_session.close()
        self.erp_session.close()

    def __mark_identity_as_new(self, customer_id, first_name, last_name, mail, dormitory_id, room):
        if first_name is None or last_name is None or mail is None or dormitory_id is None or room is None:
            return

        traffy_identity_new_query = self.traffy_session.query(IdentityNew).filter_by(customer_id=customer_id).all()

        if len(traffy_identity_new_query) == 0:
            row = IdentityNew(customer_id=customer_id,
                              first_name=first_name.strip().strip(';').strip(),
                              last_name=last_name.strip().strip(';').strip(),
                              mail=mail.strip().strip(';').strip(),
                              dormitory_id=dormitory_id,
                              room=room)
            self.traffy_session.add(row)


    def __mark_identity_as_updatable(self, identity_id, first_name, last_name, mail, dormitory_id, room):
        row = IdentityUpdate(identity_id=identity_id,
                             first_name=first_name,
                             last_name=last_name,
                             mail=mail,
                             dormitory_id=dormitory_id,
                             room=room)
        self.traffy_session.add(row)


    def __mark_identity_as_deletable(self, identity_id):
        identity_delete = self.traffy_session.query(IdentityDelete).filter_by(identity_id=identity_id).all()
        if len(identity_delete) == 0:
            row = IdentityDelete(identity_id=identity_id)
            self.traffy_session.add(row)


    def __clear_identity_updates_table(self):
        try:
            self.traffy_session.query(IdentityUpdate).delete()
            self.traffy_session.commit()
        except:
            self.traffy_session.rollback()


integration_service = IntegrationService()
integration_service.run_service()
