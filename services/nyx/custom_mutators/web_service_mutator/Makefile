CC = clang
CFLAGS = -Wall -Wextra -O3 -funroll-loops -fPIC -Wl,-Bsymbolic
LDFLAGS = -lcurl -ljson-c -lssl -lcrypto
INCLUDES = -I../../include/ -I./json -I/usr/include/json-c

OUT = web_service_mutator.so

SRC = web_service_mutator.c
AFL_SRC = ../../src/afl-performance.c

$(OUT): $(SRC)
	$(CC) $(CFLAGS) $(INCLUDES) -shared -o $(OUT) $(SRC) $(AFL_SRC) $(LDFLAGS)

debug: CFLAGS += -g -DDEBUG
debug: $(OUT)

clean:
	rm -f $(OUT)

install_deps:
	apt-get install libjson-c-dev libcurl4-openssl-dev libssl-dev
