#include "cosyvoice3.h"
#include <stdio.h>
static int drain(cv3_t2w *wav, FILE *out) {
    float audio[65536];
    int n;
    while ((n = cv3_t2w_read(wav, audio, 65536)) > 0)
        if (fwrite(audio, sizeof(float), (size_t)n, out) != (size_t)n) return -1;
    return n;
}
int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s model-dir voice-dir speaker-id output.f32\n", argv[0]);
        return 2;
    }
    cv3_llm *llm = NULL;
    cv3_t2w *wav = NULL;
    FILE *out = NULL;
    int rc = 1, n;
#define CHECK(x) do { if ((x) < 0) goto cleanup; } while (0)
    llm = cv3_llm_create(argv[1]);
    if (!llm) goto cleanup;
    wav = cv3_t2w_create(argv[1]);
    if (!wav) goto cleanup;
    CHECK(cv3_llm_load_voice(llm,argv[3],argv[2]));
    CHECK(cv3_t2w_load_voice(wav,argv[3],argv[2]));
    out=fopen(argv[4],"wb"); if (!out) goto cleanup;
    CHECK(cv3_t2w_start(wav,argv[3],100));
    CHECK(cv3_llm_start(llm,argv[3],NULL,"你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",0,0));
    int32_t token;
    while ((n=cv3_llm_next(llm,&token)) > 0) {
        if (cv3_t2w_push(wav,&token,1)!=1) goto cleanup;
        while ((n=cv3_t2w_step(wav))>0) CHECK(drain(wav,out));
        if (n<0) goto cleanup;
    }
    if (n<0 || cv3_llm_end_reason(llm)!=CV3_END_EOS) goto cleanup;
    CHECK(cv3_t2w_finish(wav));
    while (!cv3_t2w_done(wav)) { CHECK(cv3_t2w_step(wav)); CHECK(drain(wav,out)); }
    CHECK(drain(wav,out));
    rc=0;
cleanup:
    if (rc) fprintf(stderr, "Load: %s; LLM: %s; waveform: %s\n",
                    cv3_create_error(), cv3_llm_last_error(llm), cv3_t2w_last_error(wav));
    if (out && fclose(out)!=0) rc=1;
    if (cv3_t2w_destroy_owned(&wav) < 0) rc = 1;
    if (cv3_llm_destroy_owned(&llm) < 0) rc = 1;
    if (!rc) puts("Synthesis complete.");
    return rc;
}
