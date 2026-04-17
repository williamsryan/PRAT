include ../config.mk

.PHONY : really clean install

MOSQ_OBJS=mosquitto.bc \
		  actions.bc \
		  callbacks.bc \
		  connect.bc \
		  handle_auth.bc \
		  handle_connack.bc \
		  handle_disconnect.bc \
		  handle_ping.bc \
		  handle_pubackcomp.bc \
		  handle_publish.bc \
		  handle_pubrec.bc \
		  handle_pubrel.bc \
		  handle_suback.bc \
		  handle_unsuback.bc \
		  helpers.bc \
		  logging_mosq.bc \
		  loop.bc \
		  memory_mosq.bc \
		  messages_mosq.bc \
		  net_mosq_ocsp.bc \
		  net_mosq.bc \
		  options.bc \
		  packet_datatypes.bc \
		  packet_mosq.bc \
		  property_mosq.bc \
		  read_handle.bc \
		  send_connect.bc \
		  send_disconnect.bc \
		  send_mosq.bc \
		  send_publish.bc \
		  send_subscribe.bc \
		  send_unsubscribe.bc \
		  socks_mosq.bc \
		  srv_mosq.bc \
		  thread_mosq.bc \
		  time_mosq.bc \
		  tls_mosq.bc \
		  utf8_mosq.bc \
		  util_mosq.bc \
		  util_topic.bc \
		  will_mosq.bc

ALL_DEPS:=

ifeq ($(WITH_SHARED_LIBRARIES),yes)
	ALL_DEPS+=libmosquitto.so.${SOVERSION}
endif

ifeq ($(WITH_STATIC_LIBRARIES),yes)
	ALL_DEPS+=libmosquitto.a
endif

all : ${ALL_DEPS}
ifeq ($(WITH_SHARED_LIBRARIES),yes)
	#$(MAKE) -C cpp
endif

install : all
	$(INSTALL) -d "${DESTDIR}${libdir}/"
ifeq ($(WITH_SHARED_LIBRARIES),yes)
	$(INSTALL) ${STRIP_OPTS} libmosquitto.so.${SOVERSION} "${DESTDIR}${libdir}/libmosquitto.so.${SOVERSION}"
	ln -sf libmosquitto.so.${SOVERSION} "${DESTDIR}${libdir}/libmosquitto.so"
endif
ifeq ($(WITH_STATIC_LIBRARIES),yes)
	$(INSTALL) ${STRIP_OPTS} libmosquitto.a "${DESTDIR}${libdir}/libmosquitto.a"
endif
	$(INSTALL) -d "${DESTDIR}${incdir}/"
	$(INSTALL) mosquitto.h "${DESTDIR}${incdir}/mosquitto.h"
	$(INSTALL) mqtt_protocol.h "${DESTDIR}${incdir}/mqtt_protocol.h"
	$(INSTALL) -d "${DESTDIR}${libdir}/pkgconfig"
	$(INSTALL) -m644 ../libmosquitto.pc.in "${DESTDIR}${libdir}/pkgconfig/libmosquitto.pc"
	sed -i -e "s#@CMAKE_INSTALL_PREFIX@#${prefix}#" -e "s#@VERSION@#${VERSION}#" "${DESTDIR}${libdir}/pkgconfig/libmosquitto.pc"
ifeq ($(WITH_SHARED_LIBRARIES),yes)
	$(MAKE) -C cpp install
endif

uninstall :
	-rm -f "${DESTDIR}${libdir}/libmosquitto.so.${SOVERSION}"
	-rm -f "${DESTDIR}${libdir}/libmosquitto.so"
	-rm -f "${DESTDIR}${libdir}/libmosquitto.a"
	-rm -f "${DESTDIR}${incdir}/mosquitto.h"

reallyclean : clean

clean :
	-rm -f *.bc libmosquitto.so.${SOVERSION} libmosquitto.so libmosquitto.a *.gcno *.gcda klee-* *.o
	$(MAKE) -C cpp clean

libmosquitto.so.${SOVERSION} : ${MOSQ_OBJS}
	llvm-link-9 $^ -o $@

libmosquitto.a : ${MOSQ_OBJS}
	${CROSS_COMPILE}$(AR) cr $@ $^

mosquitto.bc : mosquitto.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

actions.bc : actions.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

callbacks.bc : callbacks.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

connect.bc : connect.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_auth.bc : handle_auth.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_connack.bc : handle_connack.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_disconnect.bc : handle_disconnect.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_publish.bc : handle_publish.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_ping.bc : handle_ping.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_pubackcomp.bc : handle_pubackcomp.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_pubrec.bc : handle_pubrec.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_pubrel.bc : handle_pubrel.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_suback.bc : handle_suback.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

handle_unsuback.bc : handle_unsuback.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

helpers.bc : helpers.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

logging_mosq.bc : logging_mosq.c logging_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

loop.bc : loop.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

messages_mosq.bc : messages_mosq.c messages_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

memory_mosq.bc : memory_mosq.c memory_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

net_mosq_ocsp.bc : net_mosq_ocsp.c net_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

net_mosq.bc : net_mosq.c net_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

options.bc : options.c mosquitto.h mosquitto_internal.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

packet_datatypes.bc : packet_datatypes.c packet_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

packet_mosq.bc : packet_mosq.c packet_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

property_mosq.bc : property_mosq.c property_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

read_handle.bc : read_handle.c read_handle.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_connect.bc : send_connect.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_disconnect.bc : send_disconnect.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_mosq.bc : send_mosq.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_publish.bc : send_publish.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_subscribe.bc : send_subscribe.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

send_unsubscribe.bc : send_unsubscribe.c send_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

socks_mosq.bc : socks_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

srv_mosq.bc : srv_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

thread_mosq.bc : thread_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

time_mosq.bc : time_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

tls_mosq.bc : tls_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

utf8_mosq.bc : utf8_mosq.c
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

util_mosq.bc : util_mosq.c util_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

util_topic.bc : util_topic.c util_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

will_mosq.bc : will_mosq.c will_mosq.h
	${CROSS_COMPILE}$(CC) $(LIB_CPPFLAGS) $(LIB_CFLAGS) -c $< -o $@

