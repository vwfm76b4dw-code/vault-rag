#include <bits/stdc++.h>
using namespace std;
int a[31];
int cnt,sum;
int main()
{
	int i=1;
	while(cin>>a[i]){
		if(a[i]==2){
			cnt+=2;
		}else{
			cnt=0;
			if(a[i]==1)sum++;
			else break;
		}
		sum+=cnt;
		i++;
	}
	cout<<sum;
}
