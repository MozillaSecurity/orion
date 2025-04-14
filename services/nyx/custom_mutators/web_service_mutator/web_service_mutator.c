#include "afl-fuzz.h"
#include "afl-mutations.h"
#include <curl/curl.h>
#include <json-c/json.h>
#include <openssl/evp.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct {
  afl_state_t *afl;
  uint8_t     *buf;
  size_t       buf_size;
} MyMutator;

struct memory {
  char  *response;
  size_t size;
};

size_t write_callback(void *ptr, size_t size, size_t nmemb, void *userdata) {
  size_t         realsize = size * nmemb;
  struct memory *mem = userdata;

  char *ptr_resized = realloc(mem->response, mem->size + realsize + 1);
  if (!ptr_resized) {
    perror("Unable to allocate memory for response");
    return 0;
  }

  mem->response = ptr_resized;

  memcpy(&(mem->response[mem->size]), ptr, realsize);
  mem->size += realsize;
  mem->response[mem->size] = '\0';

  return realsize;
}

char *base64_encode(const uint8_t *data, size_t len) {
  size_t out_len = 4 * ((len + 2) / 3);
  char  *out = malloc(out_len + 1);
  if (!out) {
    perror("Memory allocation failed in base64_encode");
    return NULL;
  }

  int actual = EVP_EncodeBlock(out, data, len);
  out[actual] = '\0';
  return out;
}

uint8_t *base64_decode(const char *b64, size_t *out_len) {
  size_t   len = strlen(b64);
  uint8_t *out = malloc(len);
  if (!out) {
    perror("Memory allocation failed in base64_decode");
    *out_len = 0;
    return NULL;
  }

  int decoded_len = EVP_DecodeBlock(out, b64, len);
  if (decoded_len < 0) {
    free(out);
    *out_len = 0;
    return NULL;
  }
  *out_len = decoded_len;
  return out;
}

json_object *parse_input_json(const uint8_t *buf, size_t len) {
  json_object *jobj = json_tokener_parse((const char *)buf);
  return jobj;
}

uint8_t *decode_buffer_field(json_object *input, size_t *decoded_len) {
  json_object *buffer_obj;
  if (!json_object_object_get_ex(input, "buffer", &buffer_obj) ||
      json_object_get_type(buffer_obj) != json_type_string) {
    *decoded_len = 0;
    return NULL;
  }

  const char *b64_str = json_object_get_string(buffer_obj);
  return base64_decode(b64_str, decoded_len);
}

size_t mutate_buffer(MyMutator *data, uint8_t *input, size_t input_size,
                     uint8_t *add_buf, size_t add_buf_size, size_t max_size) {
  if (max_size > data->buf_size) {
    uint8_t *ptr = realloc(data->buf, max_size);
    if (!ptr) return 0;
    data->buf = ptr;
    data->buf_size = max_size;
  }

  memcpy(data->buf, input, input_size);
  bool is_exploration = data->afl->schedule == EXPLORE ? true : false;
  return afl_mutate(data->afl, data->buf, input_size, rand_below(data->afl, 16),
                    false, is_exploration, add_buf, add_buf_size, max_size);
}

json_object *send_to_http_service(const uint8_t *buf, size_t len,
                                  MyMutator *data) {
  CURL *curl = curl_easy_init();
  if (!curl) return NULL;

  struct memory mem;
  mem.response = malloc(1);
  mem.size = 0;
  if (!mem.response) {
    perror("Unable to allocate memory for HTTP response");
    curl_easy_cleanup(curl);
    return NULL;
  }

  // curl_easy_setopt(curl, CURLOPT_VERBOSE, 1L);
  curl_easy_setopt(curl, CURLOPT_URL, "http://localhost:8080/mutate");
  curl_easy_setopt(curl, CURLOPT_POST, 1L);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, buf);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, len);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &mem);

  struct curl_slist *hs = NULL;
  hs = curl_slist_append(hs, "Content-Type: application/octet-stream");
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hs);

  CURLcode res = curl_easy_perform(curl);
  curl_slist_free_all(hs);
  curl_easy_cleanup(curl);

  if (res != CURLE_OK) {
    free(mem.response);
    return NULL;
  }

  json_object *response_json = json_tokener_parse(mem.response);
  free(mem.response);

  return response_json;
}

char *make_output_json(json_object *response, const uint8_t *mutated,
                       size_t size) {
  json_object *output = json_object_new_object();

  if (response != NULL) {
    json_object_object_foreach(response, key, val) {
      json_object_object_add(output, key, json_object_get(val));
    }
  }

  json_object_object_add(output, "buffer",
                         json_object_new_string(base64_encode(mutated, size)));

  return strdup(json_object_to_json_string(output));
}
MyMutator *afl_custom_init(afl_state_t *afl, unsigned int seed) {
  curl_global_init(CURL_GLOBAL_ALL);
  MyMutator *state = malloc(sizeof(MyMutator));
  state->afl = afl;
  state->buf = malloc(sizeof(uint8_t) * MAX_FILE);
  state->buf_size = MAX_FILE;
  return state;
}

void afl_custom_deinit(MyMutator *data) {
  if (data) {
    free(data->buf);
    free(data);
    curl_global_cleanup();
  }
}

size_t afl_custom_fuzz(MyMutator *data, uint8_t *buf, size_t buf_size,
                       uint8_t **out_buf, uint8_t *add_buf, size_t add_buf_size,
                       size_t max_size) {
  size_t   decoded_len;
  uint8_t *decoded = NULL;

  json_object *input_json = parse_input_json(buf, buf_size);
  if (input_json) {
    decoded = decode_buffer_field(input_json, &decoded_len);
    if (decoded_len == 0) {
      perror("Failed to decode buffer field.\n");
      return 0;
    }
  } else {
    // If the initial buffer isn't in JSON, just treat it as raw data.
    decoded_len = buf_size;
    decoded = malloc(buf_size);
    memcpy(decoded, buf, buf_size);
  }

  size_t mutated_size = mutate_buffer(data, decoded, decoded_len, add_buf,
                                      add_buf_size, max_size);
  if (!mutated_size) {
    perror("Failed to mutate buffer");
    free(decoded);
    return 0;
  }

  json_object *response = send_to_http_service(data->buf, mutated_size, data);
  if (!response) {
    perror("Failed to get a response from HTTP service");
    free(decoded);
    return 0;
  }

  char *output = make_output_json(response, data->buf, mutated_size);
  free(decoded);

  size_t output_size = strlen(output);
  if (output_size > max_size) {
    free(output);
    return 0;
  }

  memcpy(data->buf, output, output_size);
  *out_buf = data->buf;
  free(output);
  return output_size;
}
