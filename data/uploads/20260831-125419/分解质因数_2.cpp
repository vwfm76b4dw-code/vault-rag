#include <bits/stdc++.h>
using namespace std;
int main()
{
	int n,i=2,t;
	cin>>n;
	t=n;
	while(i<=sqrt(t)){
		while(n%i==0){
			cout<<i<<" ";
			n=n/i;
		}
		i++;
	}
	if(n>sqrt(t))cout<<n;
}
