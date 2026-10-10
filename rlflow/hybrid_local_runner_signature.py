"""Bounded Ed25519 publication signatures via the approved local libcrypto.

No private key on disk or in task-fork memory: caller creates Signer only after
the task has forked and closed all keeper descriptors. Pure crypto, not a grant.
"""
import ctypes
import hashlib
import json
import os
import re
import stat

LIBCRYPTO='/usr/lib/x86_64-linux-gnu/libcrypto.so.3'


def _library(expected_sha256=None):
    if expected_sha256 is not None:
        fd=os.open(LIBCRYPTO,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            raw=os.pread(fd,16*1024**2+1,0)
            after=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or
                    len(raw)>16*1024**2 or len(raw)!=info.st_size or
                    'sha256:'+hashlib.sha256(raw).hexdigest()!=expected_sha256 or
                    any(getattr(info,name)!=getattr(after,name) for name in
                        ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_uid'))):
                raise RuntimeError('original approved libcrypto changed')
        finally:os.close(fd)
    lib=ctypes.CDLL(LIBCRYPTO)
    pointer=ctypes.c_void_p;size=ctypes.c_size_t
    definitions={
        'EVP_PKEY_new_raw_private_key_ex':(pointer,[pointer,ctypes.c_char_p,ctypes.c_char_p,pointer,size]),
        'EVP_PKEY_new_raw_public_key_ex':(pointer,[pointer,ctypes.c_char_p,ctypes.c_char_p,pointer,size]),
        'EVP_PKEY_get_raw_public_key':(ctypes.c_int,[pointer,pointer,ctypes.POINTER(size)]),
        'EVP_PKEY_free':(None,[pointer]),'EVP_MD_CTX_new':(pointer,[]),'EVP_MD_CTX_free':(None,[pointer]),
        'OSSL_LIB_CTX_new':(pointer,[]),'OSSL_LIB_CTX_free':(None,[pointer]),
        'EVP_DigestSignInit_ex':(ctypes.c_int,[pointer,pointer,pointer,pointer,ctypes.c_char_p,pointer,pointer]),
        'EVP_DigestVerifyInit_ex':(ctypes.c_int,[pointer,pointer,pointer,pointer,ctypes.c_char_p,pointer,pointer]),
        'EVP_DigestSign':(ctypes.c_int,[pointer,pointer,ctypes.POINTER(size),pointer,size]),
        'EVP_DigestVerify':(ctypes.c_int,[pointer,pointer,size,pointer,size])}
    for name,(result,args) in definitions.items():
        fn=getattr(lib,name);fn.restype=result;fn.argtypes=args
    return lib


def encoded(value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    if len(raw)>32768:raise ValueError('bounded recovery signature payload required')
    return b'rlflow.local_cpu.recovery/1\x00'+raw


class Signer:
    def __init__(self,expected_sha256=None):
        self._lib=_library(expected_sha256);self._pid=os.getpid();self._key=None
        # Private libctx: do not load config or use the default env-configured
        # context. Require built-in default provider, with no fallback.
        self._context=self._lib.OSSL_LIB_CTX_new()
        if not self._context:raise RuntimeError('original crypto context unavailable')
        private=ctypes.create_string_buffer(os.urandom(32))
        try:self._key=self._lib.EVP_PKEY_new_raw_private_key_ex(self._context,b'ED25519',b'provider=default',private,32)
        finally:ctypes.memset(private,0,len(private))
        if not self._key:
            self.close();raise RuntimeError('original Ed25519 key generation failed')
        try:
            public=ctypes.create_string_buffer(32);size=ctypes.c_size_t(32)
            if self._lib.EVP_PKEY_get_raw_public_key(self._key,public,ctypes.byref(size))!=1 or size.value!=32:
                raise RuntimeError('original Ed25519 public key unavailable')
            self.public_key=public.raw.hex()
        except BaseException:
            self.close();raise

    def sign(self,value):
        if os.getpid()!=self._pid or not self._key:raise RuntimeError('original live publication signer required')
        context=self._lib.EVP_MD_CTX_new()
        if not context:raise RuntimeError('original signature context unavailable')
        try:
            raw=encoded(value);data=ctypes.create_string_buffer(raw)
            signature=ctypes.create_string_buffer(64);size=ctypes.c_size_t(64)
            if (self._lib.EVP_DigestSignInit_ex(context,None,None,self._context,b'provider=default',self._key,None)!=1 or
                    self._lib.EVP_DigestSign(context,signature,ctypes.byref(size),data,len(raw))!=1 or size.value!=64):
                raise RuntimeError('original Ed25519 publication signature failed')
            return signature.raw.hex()
        finally:self._lib.EVP_MD_CTX_free(context)

    def close(self):
        if os.getpid()!=self._pid:raise RuntimeError('original signer process required')
        if self._key:self._lib.EVP_PKEY_free(self._key);self._key=None
        if self._context:self._lib.OSSL_LIB_CTX_free(self._context);self._context=None


def verify(public_key,value,signature,expected_sha256=None):
    if (type(public_key) is not str or not re.fullmatch('[0-9a-f]{64}',public_key) or
            type(signature) is not str or not re.fullmatch('[0-9a-f]{128}',signature)):
        return False
    lib=_library(expected_sha256);public=ctypes.create_string_buffer(bytes.fromhex(public_key))
    libcontext=lib.OSSL_LIB_CTX_new()
    if not libcontext:raise RuntimeError('original verification libctx unavailable')
    key=lib.EVP_PKEY_new_raw_public_key_ex(libcontext,b'ED25519',b'provider=default',public,32)
    if not key:
        lib.OSSL_LIB_CTX_free(libcontext);raise RuntimeError('original Ed25519 verification key unavailable')
    context=None
    try:
        context=lib.EVP_MD_CTX_new()
        if not context:raise RuntimeError('original verification context unavailable')
        raw=encoded(value);data=ctypes.create_string_buffer(raw);sig=ctypes.create_string_buffer(bytes.fromhex(signature))
        return (lib.EVP_DigestVerifyInit_ex(context,None,None,libcontext,b'provider=default',key,None)==1 and
                lib.EVP_DigestVerify(context,sig,64,data,len(raw))==1)
    finally:
        if context:lib.EVP_MD_CTX_free(context)
        lib.EVP_PKEY_free(key)
        lib.OSSL_LIB_CTX_free(libcontext)
