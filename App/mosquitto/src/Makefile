include ../config.mk

.PHONY: all install uninstall clean reallyclean

#CFLAGS+=-coverage

ifeq ($(WITH_TLS),yes)
all : mosquitto mosquitto_passwd
else
all : mosquitto
endif

OBJS=	mosquitto.bc \
		alias_mosq.bc \
		bridge.bc \
		conf.bc \
		conf_includedir.bc \
		context.bc \
		database.bc \
		handle_auth.bc \
		handle_connack.bc \
		handle_connect.bc \
		handle_disconnect.bc \
		handle_ping.bc \
		handle_pubackcomp.bc \
		handle_publish.bc \
		handle_pubrec.bc \
		handle_pubrel.bc \
		handle_suback.bc \
		handle_subscribe.bc \
		handle_unsuback.bc \
		handle_unsubscribe.bc \
		logging.bc \
		loop.bc \
		memory_mosq.bc \
		net.bc \
		net_mosq.bc \
		net_mosq_ocsp.bc \
		packet_datatypes.bc \
		packet_mosq.bc \
		property_broker.bc \
		property_mosq.bc \
		persist_read.bc \
		persist_read_v234.bc \
		persist_read_v5.bc \
		persist_write.bc \
		persist_write_v5.bc \
		plugin.bc \
		read_handle.bc \
		security.bc \
		security_default.bc \
		send_auth.bc \
		send_connack.bc \
		send_connect.bc \
		send_disconnect.bc \
		send_mosq.bc \
		send_publish.bc \
		send_suback.bc \
		send_subscribe.bc \
		send_unsuback.bc \
		send_unsubscribe.bc \
		service.bc \
		session_expiry.bc \
		signals.bc \
		subs.bc \
		sys_tree.bc \
		time_mosq.bc \
		tls_mosq.bc \
		utf8_mosq.bc \
		util_mosq.bc \
		util_topic.bc \
		websockets.bc \
		will_delay.bc \
		will_mosq.bc

mosquitto : ${OBJS}
	${CROSS_COMPILE}${CC} ${BROKER_LDFLAGS} $^ -o $@ $(BROKER_LDADD)

mosquitto.bc : mosquitto.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

alias_mosq.bc : ../lib/alias_mosq.c ../lib/alias_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

bridge.bc : bridge.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

conf.bc : conf.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

conf_includedir.bc : conf_includedir.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

context.bc : context.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

database.bc : database.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_auth.bc : handle_auth.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_connack.bc : handle_connack.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_connect.bc : handle_connect.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_disconnect.bc : handle_disconnect.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_ping.bc : ../lib/handle_ping.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_pubackcomp.bc : ../lib/handle_pubackcomp.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_publish.bc : handle_publish.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_pubrec.bc : ../lib/handle_pubrec.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_pubrel.bc : ../lib/handle_pubrel.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_suback.bc : ../lib/handle_suback.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_subscribe.bc : handle_subscribe.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_unsuback.bc : ../lib/handle_unsuback.c ../lib/read_handle.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

handle_unsubscribe.bc : handle_unsubscribe.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

logging.bc : logging.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

loop.bc : loop.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

memory_mosq.bc : ../lib/memory_mosq.c ../lib/memory_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

net.bc : net.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

net_mosq_ocsp.bc : ../lib/net_mosq_ocsp.c ../lib/net_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

net_mosq.bc : ../lib/net_mosq.c ../lib/net_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

persist_read.bc : persist_read.c persist.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

persist_read_v234.bc : persist_read_v234.c persist.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

persist_read_v5.bc : persist_read_v5.c persist.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

persist_write.bc : persist_write.c persist.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

persist_write_v5.bc : persist_write_v5.c persist.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

packet_datatypes.bc : ../lib/packet_datatypes.c ../lib/packet_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

packet_mosq.bc : ../lib/packet_mosq.c ../lib/packet_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

property_broker.bc : property_broker.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

property_mosq.bc : ../lib/property_mosq.c ../lib/property_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

plugin.bc : plugin.c mosquitto_plugin.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

read_handle.bc : read_handle.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

security.bc : security.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

security_default.bc : security_default.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_auth.bc : send_auth.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_connect.bc : ../lib/send_connect.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_disconnect.bc : ../lib/send_disconnect.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_connack.bc : send_connack.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_mosq.bc : ../lib/send_mosq.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_publish.bc : ../lib/send_publish.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_suback.bc : send_suback.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_subscribe.bc : ../lib/send_subscribe.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_unsuback.bc : send_unsuback.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

send_unsubscribe.bc : ../lib/send_unsubscribe.c ../lib/send_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

service.bc : service.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

session_expiry.bc : session_expiry.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

signals.bc : signals.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

subs.bc : subs.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

sys_tree.bc : sys_tree.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

time_mosq.bc : ../lib/time_mosq.c ../lib/time_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

tls_mosq.bc : ../lib/tls_mosq.c
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

util_mosq.bc : ../lib/util_mosq.c ../lib/util_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

util_topic.bc : ../lib/util_topic.c ../lib/util_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

utf8_mosq.bc : ../lib/utf8_mosq.c
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

websockets.bc : websockets.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

will_delay.bc : will_delay.c mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

will_mosq.bc : ../lib/will_mosq.c ../lib/will_mosq.h
	${CROSS_COMPILE}${CC} $(BROKER_CPPFLAGS) $(BROKER_CFLAGS) -c $< -o $@

mosquitto_passwd : mosquitto_passwd.bc
	${CROSS_COMPILE}${CC} ${LDFLAGS} $^ -o $@ $(PASSWD_LDADD)

mosquitto_passwd.bc : mosquitto_passwd.c
	${CROSS_COMPILE}${CC} -I.. $(CPPFLAGS) $(CFLAGS) -c $< -o $@

plugin_defer.so : plugin_defer.c mosquitto_plugin.h mosquitto_broker.h mosquitto_broker_internal.h
	${CROSS_COMPILE}${CC} -I. -I../lib -fPIC -shared $< -o $@

install : all
	$(INSTALL) -d "${DESTDIR}$(prefix)/sbin"
	$(INSTALL) ${STRIP_OPTS} mosquitto "${DESTDIR}${prefix}/sbin/mosquitto"
	$(INSTALL) -d "${DESTDIR}$(prefix)/include"
	$(INSTALL) mosquitto_broker.h "${DESTDIR}${prefix}/include/mosquitto_broker.h"
	$(INSTALL) mosquitto_plugin.h "${DESTDIR}${prefix}/include/mosquitto_plugin.h"
ifeq ($(WITH_TLS),yes)
	$(INSTALL) -d "${DESTDIR}$(prefix)/bin"
	$(INSTALL) ${STRIP_OPTS} mosquitto_passwd "${DESTDIR}${prefix}/bin/mosquitto_passwd"
endif

uninstall :
	-rm -f "${DESTDIR}${prefix}/sbin/mosquitto"
	-rm -f "${DESTDIR}${prefix}/include/mosquitto_broker.h"
	-rm -f "${DESTDIR}${prefix}/include/mosquitto_plugin.h"
	-rm -f "${DESTDIR}${prefix}/bin/mosquitto_passwd"

clean : 
	-rm -rf *.bc mosquitto mosquitto_passwd *.gcda *.gcno klee-* *.o

reallyclean : clean
	-rm -rf *.bcrig *.db
