#include <bits/stdc++.h>
using namespace std;
char b[61]="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwx";
char a[10000001];
int x,cnt=1,m;
void f(int &cnt,int &x){
	a[cnt]=b[x%m];
	cnt++;
	x/=m;	
}
int main()
{
	cin>>x>>m;
	while(x){
		f(cnt,x);
	}
	for(int i=cnt-1;i>=1;i--){
		cout<<a[i];
	}
	return 0;
}
