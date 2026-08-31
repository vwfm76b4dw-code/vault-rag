#include<cstdio>
#include<algorithm>
#include<cstring>
#include<cmath>
#include<map>
using namespace std;
typedef long long ll;
ll n,x,ans;
//map<ll,int>mp;
int calc(ll x){
    int res=0;
    while(x){
        res++;
        x/=10;
    }
    return res;
}

void dfs(ll x,ll p){
    //printf("%lld %lld\n",x,p);
    if (p>=ans)
        return;
    if(calc(x)+(ans-p)<=n)  return;
    if (calc(x)>=n){
        ans=min(ans,p);
        return;
    }
    //mp[x]=p;
    ll tmp=x;
    bool exist[10];
    memset(exist,0,sizeof exist);
    while(tmp){
        exist[tmp%10]=1;
        tmp/=10;
    }
    for(int i=9;i>=2;i--)
        if (exist[i]){
                dfs(x*i,p+1);
        }
}

int main(){
    scanf("%lld%lld",&n,&x);
    ans=0x3f3f3f3f;
    dfs(x,0);
    if (ans == 0x3f3f3f3f)
        printf("-1");
    else
        printf("%lld\n",ans);
}
