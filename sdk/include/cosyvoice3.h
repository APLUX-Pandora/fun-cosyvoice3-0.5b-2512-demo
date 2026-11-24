/*
 * cosyvoice3.h - Fun-CosyVoice3-0.5B-2512 zero-shot text-to-speech on Qualcomm NPUs (QNN), C API.
 *
 * Two independent objects, one per model stage:
 *   cv3_llm  text -> speech tokens. One query per text segment: cv3_llm_start, then cv3_llm_next until it returns 0.
 *   cv3_t2w  speech tokens -> 24 kHz audio (flow-matching DiT + HiFT vocoder), streaming: cv3_t2w_start, then
 *            cv3_t2w_push / cv3_t2w_finish to feed tokens and cv3_t2w_step + cv3_t2w_read to get audio chunks.
 * A segment is synthesized by feeding the tokens of one cv3_llm query into one cv3_t2w stream. Objects have separate
 * inference state; explicit runtime bindings may share backend and power-client resources. Call separate objects
 * in caller-owned threads or alternately from one thread; QNN/driver determine hardware overlap.
 *
 * Voices are voice packs (.npz: the reference recording's text ids / rows, speech tokens, mel and speaker
 * embedding). Callers add and remove voice packs at run time; both objects take a voice id.
 * Inference requires models.json with "format_version": 2, "model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
 * a "resources" object for shared files, and a "targets" array declaring each SoC's files and graph names
 * under targets/<soc>_qnn248. Paths are relative to the package root. If present, "file_sizes" must list
 * the byte count of each file checked at create, including shared files, selected graphs, and any voice
 * index and voice packs. Optional "voices" points to the index next to the voices/ folder.
 * Inference create selects an installed target using the Runtime's soc_id. QCS8275 can use the QCS8625 target when
 * its own target directory is absent. A missing models.json or required model file, an unknown SoC, or a
 * package without a compatible target fails with CV3_ERR_MODEL (NULL from pointer-returning creates;
 * see cv3_create_error).
 * Stage text must already be prepared and fit one query. The native text frontend handles Chinese
 * normalization and Japanese reading and can be used separately from inference.
 *
 * All inference calls are synchronous; burst/sustained runtimes use a timer for idle power votes.
 * If an idle power vote fails, subsequent NPU execution on the affected power client returns CV3_ERR_NPU.
 * Release all inference objects sharing that client, then create new inference objects to recover.
 * The library reads files only in *_create (the model package) and in
 * *_load_voice (a voice pack), and reads a monotonic clock for the statistics. Every call is synchronous. One object
 * is not thread-safe; use it from one thread at a time. Exception: cv3_llm_abort may be called from any thread, but
 * not while the object is being destroyed.
 * Errors: a call that fails returns a CV3_ERR_* code and leaves a message in *_last_error (valid until the next call
 * on that object; cv3_create_error: until the next create in the same thread). An error inside cv3_llm_next or
 * cv3_t2w_step ends the query / stream: further calls return CV3_ERR_STATE until the next *_start.
 * Determinism: the same text, voice and seed give the same tokens; the same tokens give the same audio, whatever the
 * chunking of cv3_t2w_push and the timing between the two objects (with the same library build and NPU runtime).
 * The library is NPU-architecture neutral: tensor names, shapes and encodings come from the model package; the model
 * files are checked against the layout this library expects when an object is created (CV3_ERR_MODEL).
 */
#ifndef COSYVOICE3_H
#define COSYVOICE3_H

#include <stddef.h>
#include <stdint.h>
#include "pandora_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#define CV3_API __declspec(dllexport)
#else
#define CV3_API __attribute__((visibility("default")))
#endif

#define CV3_VERSION "1.0.0"

/* return codes: >= 0 success or a count, < 0 an error */
#define CV3_OK 0
#define CV3_ERR_ARG -1      /* bad argument (unknown voice, invalid UTF-8, ...) */
#define CV3_ERR_MODEL -2    /* model file missing, malformed or of the wrong shape */
#define CV3_ERR_NPU -3      /* the vendor runtime failed */
#define CV3_ERR_STATE -4    /* call not valid in the current state */
#define CV3_ERR_INTERNAL -5 /* anything unexpected (out of memory, ...) */

CV3_API const char *cv3_version(void);
/* Reference conditioning helpers run synchronously on the Runtime CPU owner.
 * Pass NULL to use the default Runtime. If supplied, the Runtime must stay valid until return.
 * Projection: row-major float32 A[m,k]*B[k,n].
 * reduction0: fixed reference-GEMM order; reduction1: unfused scalar resampling order.
 * Valid nonoverlapping output is caller-owned.
 * Positive dimensions, each matrix at most2^28 floats; no input/output buffer retained.
 * Returns CV3_OK or error via cv3_create_error. No QNN model is loaded. */
CV3_API int cv3_reference_project(pandora_runtime_t *,const float *a,const float *b,float *out,
                                uint32_t m,uint32_t k,uint32_t n,uint32_t reduction);
/* Reference mel features over validated/resampled mono PCM,3-10seconds.
 * kind0:16kHz Whisper [128,T]; kind1:16kHz mean-centred Kaldi [T,80];
 * kind2:24kHz prompt [80,T]. Query exact dimensions before allocating output.
 * assets is the matching SDK clone_assets.npz, read on the Runtime CPU owner.
 * precision32 rounds FFT complex components to float32;64 keeps double precision.
 * Both produce caller-owned float32 output; exact count and no overlap required.
 * No buffers or assets retained after synchronous return; output unspecified on error.
 * Error text: cv3_create_error. No QNN graph is loaded by these calls. */
CV3_API int cv3_reference_feature_shape(uint32_t kind,uint64_t samples,uint32_t *rows,uint32_t *columns);
CV3_API int cv3_reference_features(pandora_runtime_t *,uint32_t kind,const float *pcm,uint64_t samples,const char *assets,uint32_t precision,float *output,uint64_t output_count);
/* Reference-feature FFT: row-major float32 input; interleaved real/imag float64
 * output, rows*(n/2+1)*2 doubles. n is400/512/1920, rows1..4096,
 * columns1..n; zero pads each row. Counts must match exactly; no aliasing.
 * Synchronous on the Runtime CPU owner; no QNN model is loaded.
 * Caller retains both buffers; neither is retained after return. Output is unspecified on error; diagnostics via
 * cv3_create_error. Double working/output precision; callers explicitly
 * convert to complex64 to match NumPy2 float32-input result precision. */
CV3_API int cv3_reference_rfft(pandora_runtime_t *runtime,const float *input,uint64_t input_count,double *output,uint64_t output_count,uint32_t rows,uint32_t columns,uint32_t n);
CV3_API const char *cv3_create_error(void); /* last failed *_create (thread-local) */
/* Compatibility no-op: buffer protection is automatic; process policy is never changed. */
CV3_API int cv3_prepare_process(void);

/* Process-local SDK-owned context-buffer diagnostics; never exposes addresses or model bytes.
 * Initialize struct_size=sizeof(cv3_protection_stats), abi_version=1. Counters apply to
 * this process only. lock_failures is cumulative; last_lock_errno is the last failure.
 * Third-party runtime copies are outside this allocation scope. */
typedef struct {
    uint32_t struct_size;
    uint32_t abi_version;
    uint64_t active_buffers;
    uint64_t dump_excluded_bytes;
    uint64_t locked_bytes;
    uint64_t lock_failures;
    int32_t last_lock_errno;
    uint32_t reserved;
} cv3_protection_stats;
CV3_API int cv3_get_protection_stats(cv3_protection_stats *out);

/* ------------------------------------------------------------------------------------------------------------ LLM */

typedef struct cv3_llm cv3_llm;

/* end reasons of a query */
#define CV3_END_NONE 0      /* still running */
#define CV3_END_EOS 1       /* the model ended the speech */
#define CV3_END_LIMIT 2     /* max_tokens reached */
#define CV3_END_ABORTED 3   /* cv3_llm_abort */

/* model_dir: the model package directory containing models.json.
 * NULL on failure, see cv3_create_error. */
CV3_API cv3_llm *cv3_llm_create(const char *model_dir);
/* Runtime binding; NULL runtime creates default configuration. Output stays owned across interruptions. */
CV3_API int cv3_llm_create_with_runtime(const char *model_dir, pandora_runtime_t *runtime, cv3_llm **out);
CV3_API int cv3_llm_destroy_owned(cv3_llm **owner);
CV3_API void cv3_llm_destroy(cv3_llm *llm);
CV3_API const char *cv3_llm_last_error(cv3_llm *llm);

/* Start a query: a voice id, an optional instruction, one normalized text segment (UTF-8), a sampling seed and a
 * token cap.
 * instruct NULL or "": zero-shot cloning, the LLM is prompted with the voice's reference text and speech tokens.
 * Otherwise the LLM is prompted with the instruction instead (dialect, emotion, speed, volume, ... e.g. "请用四川话表达。",
 * "请非常开心地说一句话。"); the voice still sets the timbre through token2wav. The library adds the model's instruction
 * template ("You are a helpful assistant. " ... "<|endofprompt|>"); an instruction that already contains
 * <|endofprompt|> is used verbatim.
 * max_tokens <= 0: the model's own cap (max_ratio of the LLM config, 20 tokens per text token) limited by the
 * context. A positive value caps generation even below the model's usual minimum before EOS sampling.
 * The demo passes the DiT budget of the segment. A running query is replaced; a pending cv3_llm_abort is cleared.
 * CV3_ERR_ARG if the query does not fit the context (see cv3_llm_prompt_rows). */
CV3_API int cv3_llm_start(cv3_llm *llm, const char *voice, const char *instruct, const char *text, uint32_t seed,
                          int32_t max_tokens);

/* LLM context rows taken by the prompt of a query with this voice and instruction (NULL / "": the voice prompt), for
 * the caller's segment budget. The query (prompt rows + text tokens + 1) is prefilled in chunks of 128 rows after a
 * short fixed prefix: the prefix plus the query rounded up to a multiple of 128 must fit the context (1024; the
 * prefix of this model package: 1 row); the generated tokens then use the rest of the context after the prefix and
 * the query (the query ends with CV3_END_LIMIT when it is full). */
CV3_API int cv3_llm_prompt_rows(cv3_llm *llm, const char *voice, const char *instruct);
/* text tokens of a UTF-8 string (the segment budget counts them) */
CV3_API int cv3_llm_count_tokens(cv3_llm *llm, const char *text);

/* Add a prepared voice directory (or explicit legacy .npz) under this id, or replace the voice with this id; remove a voice. Add / remove a voice in
 * both objects. A running query keeps its prompt (it is copied at start). */
CV3_API int cv3_llm_load_voice(cv3_llm *llm, const char *voice, const char *npz_path);
CV3_API int cv3_llm_unload_voice(cv3_llm *llm, const char *voice);

/* Generate the next speech token (the first call runs the prefill). Returns 1 and writes *token, or 0 when the query
 * has ended (cv3_llm_end_reason), or an error. */
CV3_API int cv3_llm_next(cv3_llm *llm, int32_t *token);

CV3_API int cv3_llm_end_reason(cv3_llm *llm);
/* Stop the started query after its current step; the next cv3_llm_next returns 0 with CV3_END_ABORTED. Any thread
 * (not during cv3_llm_destroy). An abort before cv3_llm_start has no effect on the new query. */
CV3_API void cv3_llm_abort(cv3_llm *llm);

typedef struct {
    int32_t text_tokens;     /* text tokens of the segment */
    int32_t query_rows;      /* LLM input rows (prompt text + text + task + prompt speech) */
    int32_t tokens;          /* speech tokens generated so far */
    int32_t max_tokens;      /* effective cap */
    double ms_npu, ms_host;  /* this query */
} cv3_llm_stats;
CV3_API int cv3_llm_get_stats(cv3_llm *llm, cv3_llm_stats *out);

/* Native CPU text processing. Optional Japanese dictionary must be the qualified
 * UTF-8 UniDic102 directory (load is lazy). model_dir resolves shared resources
 * through models.json resources. If models.json is absent, text-only use also
 * accepts manifest.json format 1 with tokenizer and text_normalizer in files
 * or extras. Text-only use requires no installed NPU target.
 * operation:0 prepare(language),1 normalize string,2 normalize+split list,
 * 3 tokenizer IDs list,4 split(language),5 Japanese-kana boolean.
 * text/language are NUL-terminated UTF-8, at most1MiB each. Returned JSON UTF-8
 * is borrowed until the next successful run or destruction. Copy before reuse.
 * Failed calls leave json_result untouched. Calls/destroy require serialization.
 * NULL selects the default Runtime. Destroy in the creating process. */
typedef struct cv3_text_frontend cv3_text_frontend;
CV3_API int cv3_text_frontend_create(const char *model_dir,const char *japanese_dictionary,
    pandora_runtime_t *,cv3_text_frontend **out);
CV3_API int cv3_text_frontend_run(cv3_text_frontend *,uint32_t operation,const char *text,
    const char *language,const char **json_result);
CV3_API int cv3_text_frontend_destroy_owned(cv3_text_frontend **owner);

/* General reference media adaptation, fixed sinc/Hann6/0.99 profile.
 * original>=16000, target16000/24000,1..10seconds worth of samples.
 * output_count must equal ceil(samples*target/original); no buffer overlap.
 * NULL Runtime uses the default settings. */
CV3_API int cv3_reference_resample(pandora_runtime_t *,const float *input,uint64_t samples,
    uint32_t original,uint32_t target,float *output,uint64_t output_count);

/* ----------------------------------------------------------------------------------------------------- token2wav */

typedef struct cv3_t2w cv3_t2w;

/* model_dir: the model package directory containing models.json. NULL on failure, see cv3_create_error.
 * A stream: cv3_t2w_start -> cv3_t2w_push (any number of times) -> cv3_t2w_finish, with cv3_t2w_step + cv3_t2w_read
 * whenever the caller wants audio, until cv3_t2w_done and an empty queue. cv3_t2w_start replaces a running stream.
 * Before the first start cv3_t2w_done is 1. */
CV3_API cv3_t2w *cv3_t2w_create(const char *model_dir);
/* Runtime binding; NULL runtime creates default configuration. Output stays owned across interruptions. */
CV3_API int cv3_t2w_create_with_runtime(const char *model_dir, pandora_runtime_t *runtime, cv3_t2w **out);
CV3_API int cv3_t2w_destroy_owned(cv3_t2w **owner);
CV3_API void cv3_t2w_destroy(cv3_t2w *t2w);
CV3_API const char *cv3_t2w_last_error(cv3_t2w *t2w);
/* Maximum supported mel-frame bucket of this loaded native engine, or ARG for NULL. */
CV3_API int cv3_t2w_max_frames(cv3_t2w *t2w);

/* Add a prepared voice directory (or explicit legacy .npz) under this id, or replace it (not the voice of a running stream: CV3_ERR_STATE until
 * cv3_t2w_done); remove a voice (a stream of that voice that has not finished is dropped: start a new one). */
CV3_API int cv3_t2w_load_voice(cv3_t2w *t2w, const char *voice, const char *npz_path);
CV3_API int cv3_t2w_unload_voice(cv3_t2w *t2w, const char *voice);

/* Start a stream for one segment. hop_max: speech tokens per chunk after the ramp 25 (+ prompt alignment) -> 50 ->
 * 100 -> ..., 100 (upstream) or 200 (fewer recomputations on long segments); <= 0 = 200; 1..24: CV3_ERR_ARG. */
CV3_API int cv3_t2w_start(cv3_t2w *t2w, const char *voice, int32_t hop_max);
/* Append speech tokens (any chunking). Returns how many were accepted: a segment holds at most (largest DiT bucket) / 2
 * - (voice prompt tokens) tokens, the rest is dropped (the caller's segment budget should stay below). */
CV3_API int cv3_t2w_push(cv3_t2w *t2w, const int32_t *tokens, int32_t n);
/* No more tokens for this segment. */
CV3_API int cv3_t2w_finish(cv3_t2w *t2w);
/* Discard the current stream; the next start starts a fresh one. */
CV3_API int cv3_t2w_abort(cv3_t2w *t2w);
/* Compute the next chunk if enough tokens are there (or the stream is finished): returns the number of samples
 * added to the output queue (> 0), 0 if more tokens are needed or the stream is done (cv3_t2w_done). */
CV3_API int cv3_t2w_step(cv3_t2w *t2w);
/* Drain up to cap samples (float, 24 kHz mono) from the output queue; returns the number written. */
CV3_API int cv3_t2w_read(cv3_t2w *t2w, float *out, int32_t cap);
/* 1 when the last chunk has been computed (the queue may still hold samples). */
CV3_API int cv3_t2w_done(cv3_t2w *t2w);

typedef struct {
    int32_t tokens;          /* tokens accepted */
    int32_t chunks;          /* chunks computed */
    int32_t samples;         /* samples produced */
    int32_t last_n;          /* DiT sequence length (mel frames incl. prompt) of the last chunk */
    double ms_npu, ms_host;  /* this stream */
} cv3_t2w_stats;
CV3_API int cv3_t2w_get_stats(cv3_t2w *t2w, cv3_t2w_stats *out);

#ifdef CV3_SDK_INTERNAL
/* Reserved for the bundled Python binding. All output slots must start NULL.
 * A successful call transfers ownership of all three handles to the caller. */
CV3_API int cv3_internal_tts_create(const char *model_dir, const char *japanese_dictionary,
                                   pandora_runtime_t *runtime, cv3_llm **llm,
                                   cv3_t2w **t2w, cv3_text_frontend **frontend);
#endif

#ifdef __cplusplus
}
#endif

#endif /* COSYVOICE3_H */
