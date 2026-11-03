#version 330 core
in vec2 uv;
out vec4 fragColor;
uniform samplerBuffer triangles, nodes, materials;
uniform sampler2DArray heights, albedos;
uniform sampler2D environmentMap;
uniform vec2 resolution;
uniform vec3 eye, target, cameraUp, lightPosition, lightColor;
uniform float fieldOfView, parallelScale, lightPower, lightSize, ambientLight, environmentStrength;
uniform int parallelCamera, shadowSamples, maxDepth, useDiffuse, useSpecular;
uniform bool useEnvironment, useReflection, useRefraction, useBump, useShadows;
const float FAR=1e20;
const float EPS=0.00004;
float radicalInverse(int value) {
    float result=0.0, factor=.5;
    for(int bit=0;bit<4;++bit) {
        result+=float(value&1)*factor; value>>=1; factor*=.5;
    }
    return result;
}
vec4 tri(int i,int j) { return texelFetch(triangles,i*8+j); }
vec4 mat(int i,int j) { return texelFetch(materials,i*5+j); }
float boxNear(vec3 o,vec3 d,vec3 low,vec3 high,float limit) {
    vec3 safeD=vec3(abs(d.x)<1e-12 ? 1e-12:d.x,
                    abs(d.y)<1e-12 ? 1e-12:d.y,
                    abs(d.z)<1e-12 ? 1e-12:d.z);
    vec3 a=(low-o)/safeD,b=(high-o)/safeD;
    vec3 nearT=min(a,b),farT=max(a,b);
    float lo=max(max(nearT.x,nearT.y),max(nearT.z,0.0));
    float hi=min(min(farT.x,farT.y),min(farT.z,limit));
    return hi>=lo ? lo:FAR;
}
// 双面 Möller–Trumbore 求交；返回 bary=(u,v)，w=1-u-v。
bool triangleHit(int id,vec3 o,vec3 d,inout float distance,out vec2 bary) {
    vec3 p0=tri(id,0).xyz,e1=tri(id,1).xyz,e2=tri(id,2).xyz;
    vec3 p=cross(d,e2);
    float det=dot(e1,p);
    if(abs(det)<1e-11) return false;
    vec3 t=o-p0;
    float u=dot(t,p)/det;
    if(u<0.0 || u>1.0) return false;
    vec3 q=cross(t,e1);
    float v=dot(d,q)/det;
    if(v<0.0 || u+v>1.0) return false;
    float hit=dot(e2,q)/det;
    if(hit<EPS || hit>=distance) return false;
    distance=hit; bary=vec2(u,v); return true;
}
int intersectScene(vec3 o,vec3 d,out float distance,out vec2 bary) {
    int pending[64]; int count=1; pending[0]=0;
    distance=FAR; int closest=-1;
    while(count>0) {
        int id=pending[--count];
        vec4 low=texelFetch(nodes,id*2),high=texelFetch(nodes,id*2+1);
        if(boxNear(o,d,low.xyz,high.xyz,distance)==FAR) continue;
        if(high.w>0.0) {
            int start=int(low.w),size=int(high.w);
            for(int i=0;i<size;++i) {
                vec2 b;
                if(triangleHit(start+i,o,d,distance,b)) { closest=start+i; bary=b; }
            }
        } else {
            int left=int(low.w),right=int(-high.w)-1;
            float a=boxNear(o,d,texelFetch(nodes,left*2).xyz,texelFetch(nodes,left*2+1).xyz,distance);
            float b=boxNear(o,d,texelFetch(nodes,right*2).xyz,texelFetch(nodes,right*2+1).xyz,distance);
            // 平衡树最多约18层（上限100万面、每叶8面），64项栈留有余量。
            if(a<b) {
                if(b<FAR) pending[count++]=right;
                if(a<FAR) pending[count++]=left;
            } else {
                if(a<FAR) pending[count++]=left;
                if(b<FAR) pending[count++]=right;
            }
        }
    }
    return closest;
}
vec2 triangleUV(int id,vec2 b) {
    vec4 a=tri(id,6); vec2 c=tri(id,7).xy;
    return a.xy*(1.0-b.x-b.y)+a.zw*b.x+c*b.y;
}
vec3 surfaceNormal(int id,vec2 bary,int materialId,out vec3 geometric) {
    vec3 e1=tri(id,1).xyz,e2=tri(id,2).xyz;
    geometric=normalize(cross(e1,e2));
    vec3 n=normalize(tri(id,3).xyz*(1.0-bary.x-bary.y)+tri(id,4).xyz*bary.x+tri(id,5).xyz*bary.y);
    if(dot(n,geometric)<0.0) geometric=-geometric;
    vec4 bump=mat(materialId,2);
    if(useBump && bump.w>=0.0 && abs(bump.x)>0.0) {
        vec4 a=tri(id,6); vec2 duv1=a.zw-a.xy,duv2=tri(id,7).xy-a.xy;
        float det=duv1.x*duv2.y-duv1.y*duv2.x;
        if(abs(det)>1e-9) {
            vec3 pu=(e1*duv2.y-e2*duv1.y)/det,pv=(e2*duv1.x-e1*duv2.x)/det;
            pu-=n*dot(n,pu); pv-=n*dot(n,pv);
            vec2 stepUV=1.0/vec2(textureSize(heights,0).xy),q=triangleUV(id,bary)*bump.yz;
            float layer=bump.w;
            float hu=(textureLod(heights,vec3(q+vec2(stepUV.x,0),layer),0).r-
                      textureLod(heights,vec3(q-vec2(stepUV.x,0),layer),0).r)/(2.0*stepUV.x)*bump.y;
            float hv=(textureLod(heights,vec3(q+vec2(0,stepUV.y),layer),0).r-
                      textureLod(heights,vec3(q-vec2(0,stepUV.y),layer),0).r)/(2.0*stepUV.y)*bump.z;
            float aa=dot(pu,pu),bb=dot(pu,pv),cc=dot(pv,pv),g=aa*cc-bb*bb;
            if(g>1e-12) n=normalize(n-bump.x*((cc*hu-bb*hv)*pu+(aa*hv-bb*hu)*pv)/g);
        }
    }
    return n;
}
vec3 environment(vec3 d) {
    if(useEnvironment) {
        vec2 q=vec2(atan(d.z,d.x)/(2.0*3.14159265)+.5,asin(clamp(d.y,-1.0,1.0))/3.14159265+.5);
        return textureLod(environmentMap,q,0).rgb*environmentStrength;
    }
    return mix(vec3(.09,.11,.15),vec3(.62,.75,.94),clamp(d.y*.5+.5,0.0,1.0))*environmentStrength;
}
vec3 visibility(vec3 p,vec3 l,float remaining) {
    if(!useShadows) return vec3(1);
    vec3 result=vec3(1);
    for(int step=0;step<16;++step) {
        float t; vec2 b; int id=intersectScene(p,l,t,b);
        if(id<0 || t>=remaining) return result;
        int m=int(tri(id,7).z);
        if(max(mat(m,3).r,max(mat(m,3).g,mat(m,3).b))>0.0) return result;
        float transmission=useRefraction ? mat(m,1).x:0.0;
        if(transmission<.01) return vec3(0);
        result*=sqrt(transmission)*mix(vec3(1),mat(m,0).rgb,.13);
        p+=l*(t+EPS*3.0); remaining-=t+EPS*3.0;
    }
    return vec3(0); // 未能走出多个透明表面时保守遮挡。
}
struct Ray { vec3 o; vec3 d; vec3 weight; int depth; int medium; };
vec3 trace(vec3 o,vec3 d) {
    Ray rays[16]; int count=1; rays[0]=Ray(o,d,vec3(1),0,-1);
    vec3 result=vec3(0);
    for(int iteration=0;iteration<128;++iteration) {
        if(count==0) break;
        Ray ray=rays[--count];
        float distance; vec2 bary; int id=intersectScene(ray.o,ray.d,distance,bary);
        if(id<0) { result+=ray.weight*environment(ray.d); continue; }
        if(ray.medium>=0) ray.weight*=exp(-(vec3(1)-mat(ray.medium,0).rgb)*distance*.7);
        int m=int(tri(id,7).z);
        vec4 base=mat(m,0),optics=mat(m,1),emission=mat(m,3);
        result+=ray.weight*emission.rgb;
        vec3 p=ray.o+distance*ray.d,g;
        vec3 n=surfaceNormal(id,bary,m,g);
        bool entering=dot(ray.d,g)<0.0;
        if(!entering) { n=-n; g=-g; }
        if(dot(n,g)<0.0) n=-n;
        vec3 color=base.rgb;
        if(emission.w>=0.0) color*=textureLod(albedos,vec3(triangleUV(id,bary),emission.w),0).rgb;
        float mirror=useReflection ? base.w:0.0;
        float transmission=useRefraction ? optics.x:0.0;
        vec3 lighting=color*ambientLight;
        for(int sampleIndex=0;sampleIndex<8;++sampleIndex) {
            if(sampleIndex>=shadowSamples || lightPower<=0.0) break;
            vec2 offset=vec2((float(sampleIndex)+.5)/float(shadowSamples),
                fract(radicalInverse(sampleIndex)+.5/float(shadowSamples)))-.5;
            vec3 lp=lightPosition+vec3(offset.x,0,offset.y)*lightSize;
            vec3 toLight=lp-p; float ld=length(toLight); vec3 l=toLight/max(ld,1e-8);
            float diffuse=max(dot(n,l),0.0);
            if(diffuse>0.0) {
                vec3 visible=visibility(p+g*EPS*3.0,l,ld);
                float attenuation=lightPower/(1.0+.045*ld*ld);
                float specular=pow(max(dot(n,normalize(l-ray.d)),0.0),optics.z)*optics.w;
                lighting+=visible*lightColor*attenuation/float(shadowSamples)*
                    (color*diffuse*float(useDiffuse)*mat(m,4).x+vec3(specular*.22*float(useSpecular)));
            }
        }
        result+=ray.weight*(1.0-mirror)*(1.0-transmission)*lighting;
        if(ray.depth>=maxDepth) continue;
        float rw=mirror,tw=0.0; vec3 refracted=vec3(0);
        if(transmission>0.0) {
            float etaI=ray.medium<0 ? 1.0:mat(ray.medium,1).y,etaT=entering ? optics.y:1.0;
            float r0=(etaI-etaT)/(etaI+etaT); r0*=r0;
            float f=r0+(1.0-r0)*pow(1.0-clamp(-dot(ray.d,n),0.0,1.0),5.0);
            refracted=refract(ray.d,n,etaI/etaT);
            if(dot(refracted,refracted)<1e-8) f=1.0;
            rw+=(1.0-mirror)*transmission*f;
            tw=(1.0-mirror)*transmission*(1.0-f);
        }
        if(tw>.001) {
            vec3 w=ray.weight*tw;
            if(max(w.r,max(w.g,w.b))>.003) {
                if(dot(refracted,g)>0.0) refracted=refract(ray.d,g,(ray.medium<0?1.0:mat(ray.medium,1).y)/(entering?optics.y:1.0));
                if(dot(refracted,refracted)<1e-10) rw+=tw;
                else rays[count++]=Ray(p-g*EPS*3.0,normalize(refracted),w,ray.depth+1,entering?m:-1);
            }
        }
        if(rw>.001) {
            vec3 w=ray.weight*rw;
            if(transmission<.01) w*=mix(vec3(1),color,.45);
            if(max(w.r,max(w.g,w.b))>.003) {
                vec3 reflected=reflect(ray.d,n);
                if(dot(reflected,g)<=0.0) reflected=reflect(ray.d,g);
                rays[count++]=Ray(p+g*EPS*3.0,reflected,w,ray.depth+1,ray.medium);
            }
        }
    }
    return result;
}
void main() {
    vec2 screen=gl_FragCoord.xy/resolution*2.0-1.0;
    screen.x*=resolution.x/resolution.y;
    vec3 f=normalize(target-eye),r=normalize(cross(f,cameraUp)),up=cross(r,f);
    vec3 o=eye,d;
    if(parallelCamera!=0) { o+=(r*screen.x+up*screen.y)*parallelScale; d=f; }
    else d=normalize(f+(r*screen.x+up*screen.y)*tan(radians(fieldOfView)*.5));
    vec3 c=trace(o,d);
    fragColor=vec4(c,1);
}
