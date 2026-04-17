include ../config.mk

.PHONY: all install uninstall reallyclean clean static static_pub static_sub static_rr

ifeq ($(WITH_SHARED_LIBRARIES),yes)
SHARED_DEP:=../lib/libmosquitto.so.${SOVERSION}
endif

ifeq ($(WITH_SHARED_LIBRARIES),yes)
ALL_DEPS:= mosquitto_pub mosquitto_sub mosquitto_rr
else
ifeq ($(WITH_STATIC_LIBRARIES),yes)
ALL_DEPS:= static_pub static_sub static_rr
endif
endif

all : ${ALL_DEPS}

static : static_pub static_sub static_rr
	# This makes mosquitto_pub/sub/rr versions that are statically linked with
	# libmosquitto only.

static_pub : pub_client.bc pub_shared.bc client_props.bc client_shared.bc ../lib/libmosquitto.a
	${CROSS_COMPILE}${CC} $^ -o mosquitto_pub ${CLIENT_LDFLAGS} ${STATIC_LIB_DEPS}

static_sub : sub_client.bc sub_client_output.bc client_props.bc client_shared.bc ../lib/libmosquitto.a
	${CROSS_COMPILE}${CC} $^ -o mosquitto_sub ${CLIENT_LDFLAGS} ${STATIC_LIB_DEPS}

static_rr : rr_client.bc client_props.bc client_shared.bc pub_shared.bc sub_client_output.bc ../lib/libmosquitto.a
	${CROSS_COMPILE}${CC} $^ -o mosquitto_rr ${CLIENT_LDFLAGS} ${STATIC_LIB_DEPS}

mosquitto_pub : pub_client.bc pub_shared.bc client_shared.bc client_props.bc
	llvm-link-9 $^ -o $@ $(CLIENT_LDADD)

mosquitto_sub : sub_client.bc sub_client_output.bc client_shared.bc client_props.bc
	llvm-link-9 $^ -o $@ $(CLIENT_LDADD)

mosquitto_rr : rr_client.bc client_shared.bc client_props.bc pub_shared.bc sub_client_output.bc
	llvm-link-9 $^ -o $@ $(CLIENT_LDADD)

pub_client.bc : pub_client.c ${SHARED_DEP}
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

pub_shared.bc : pub_shared.c ${SHARED_DEP}
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

sub_client.bc : sub_client.c ${SHARED_DEP}
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

sub_client_output.bc : sub_client_output.c ${SHARED_DEP}
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

rr_client.bc : rr_client.c ${SHARED_DEP}
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

client_shared.bc : client_shared.c client_shared.h
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

client_props.bc : client_props.c client_shared.h
	${CROSS_COMPILE}${CC} $(CLIENT_CPPFLAGS) $(CLIENT_CFLAGS) -c $< -o $@

../lib/libmosquitto.so.${SOVERSION} :
	$(MAKE) -C ../lib

../lib/libmosquitto.a :
	$(MAKE) -C ../lib libmosquitto.a

install : all
	$(INSTALL) -d "${DESTDIR}$(prefix)/bin"
	$(INSTALL) ${STRIP_OPTS} mosquitto_pub "${DESTDIR}${prefix}/bin/mosquitto_pub"
	$(INSTALL) ${STRIP_OPTS} mosquitto_sub "${DESTDIR}${prefix}/bin/mosquitto_sub"
	$(INSTALL) ${STRIP_OPTS} mosquitto_rr "${DESTDIR}${prefix}/bin/mosquitto_rr"

uninstall :
	-rm -f "${DESTDIR}${prefix}/bin/mosquitto_pub"
	-rm -f "${DESTDIR}${prefix}/bin/mosquitto_sub"
	-rm -f "${DESTDIR}${prefix}/bin/mosquitto_rr"

reallyclean : clean

clean : 
	rm -rf *.bc mosquitto_pub mosquitto_sub mosquitto_rr *.gcda *.gcno klee-*
