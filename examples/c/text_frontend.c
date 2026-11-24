/* Complete C99 client of the native text ABI; no model algorithm here. */
#include "cosyvoice3.h"
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
    cv3_text_frontend *frontend=NULL;
    const char *result=NULL;
    const char *dictionary=NULL;
    int rc=1;
    if(argc!=4 && argc!=5) {
        fprintf(stderr,"Usage: %s model-root language UTF-8-text [UniDic-directory]\n",argv[0]);
        return 2;
    }
    if(argc==5 && strcmp(argv[4],"-")) dictionary=argv[4];
    if(cv3_text_frontend_create(argv[1],dictionary,NULL,&frontend)) goto cleanup;
    if(cv3_text_frontend_run(frontend,0,argv[3],argv[2],&result)) goto cleanup;
    /* Copy/use borrowed JSON before the next call or destruction. */
    if(printf("%s\n",result)<0) goto cleanup;
    rc=0;
cleanup:
    if(rc) fprintf(stderr,"Text preparation failed: %s\n",cv3_create_error());
    if(frontend && cv3_text_frontend_destroy_owned(&frontend)) rc=1;
    return rc;
}
