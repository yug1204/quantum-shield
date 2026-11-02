#include <openssl/rsa.h>
#include <openssl/md5.h>

int make_key(void) {
    RSA *rsa = RSA_new();
    unsigned char out[MD5_DIGEST_LENGTH];
    return rsa != 0;
}
